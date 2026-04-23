"""
将format.json中的数据进行向量化并存储到LanceDB数据库。
"""
import os
import json
import lancedb
import numpy as np
from pathlib import Path
from openai import OpenAI
from typing import List, Dict, Any
from pypinyin import lazy_pinyin, Style
from ...setting.settings import settings
from ...setting.env_loader import get_api_key
from ...setting.paths import get_project_root
from ...logging.logging import setup_logger, log_success, log_error, log_module_start

def to_pinyin(text: str) -> str:
    """
    将中文文本转换为拼音（小写，无空格）。
    
    Args:
        text: 中文文本
    
    Returns:
        str: 拼音字符串
    """
    pinyin_list = lazy_pinyin(text, style=Style.NORMAL)
    return ''.join(pinyin_list).lower()

def load_data(json_file: str, logger) -> List[Dict[str, Any]]:
    """加载JSON数据文件。"""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data['data']
    except Exception as e:
        log_error(logger, f"加载数据文件失败: {e}", "Tagvectorize")
        raise

def get_embeddings_batched(texts: List[str], client: OpenAI, logger, dimension: int, model: str, batch_size: int = 10) -> List[List[float]]:
    """Batch process texts to get embeddings."""
    embeddings = []
    total = len(texts)
    
    for i in range(0, total, batch_size):
        batch_texts = texts[i : i + batch_size]
        # Clean texts to avoid issues
        cleaned_batch = [t.replace("\n", " ") if t else "" for t in batch_texts]
        
        try:
            response = client.embeddings.create(
                model=model,
                input=cleaned_batch
            )
            batch_embeddings = [data.embedding for data in response.data]
            embeddings.extend(batch_embeddings)
            
            log_success(logger, f"向量化进度: {min(i + batch_size, total)}/{total}", "Tagvectorize")
            
        except Exception as e:
            log_error(logger, f"批量向量化失败 (batch {i}-{i+batch_size}): {e}", "Tagvectorize")
            # Fallback: fill with zero vectors to maintain alignment
            embeddings.extend([[0.0] * dimension] * len(batch_texts))
            
    return embeddings

def get_existing_ids(db_path: str, table_name: str, logger) -> set:
    """获取已存在数据库中的ID集合。"""
    try:
        db = lancedb.connect(db_path)
        if table_name in db.table_names():
            table = db.open_table(table_name)
            existing_ids = set()
            # 使用to_pandas()方法获取数据
            df = table.to_pandas()
            existing_ids = set(df['id'].tolist())
            return existing_ids
        return set()
    except Exception as e:
        log_error(logger, f"读取现有数据库失败: {e}", "Tagvectorize")
        return set()

def vectorize_and_store(
    topic_name: str = "控烟",
    format_json_path: str = None,
    vector_db_path: str = None,
    rebuild: bool = False,
    batch_size: int = 500
):
    """
    主函数：向量化数据并存储到LanceDB数据库（批量处理版）。
    
    Args:
        topic_name: RAG主题名称
        rebuild: 是否重建数据库
        batch_size: 批处理大小
    """
    # 初始化logger
    logger = setup_logger(f"Tagvectorize_{topic_name}", "default")
    log_module_start(logger, "Tagvectorize", f"开始向量化数据 (Batch Mode) - 主题: {topic_name}")
    
    try:
        from ..embedding import get_sync_client
        client, model, dimension = get_sync_client()
        log_success(logger, f"客户端初始化成功 (Model: {model})", "Tagvectorize")
        
        # 加载数据
        if format_json_path:
            format_json_path = Path(format_json_path)
        else:
            project_root = get_project_root()
            format_json_path = project_root / "src" / "utils" / "rag" / "tagrag" / "format_db" / f"{topic_name}.json"

        if not format_json_path.exists():
            log_error(logger, f"主题数据文件不存在: {format_json_path}", "Tagvectorize")
            raise FileNotFoundError(f"主题数据文件不存在: {format_json_path}")

        data = load_data(str(format_json_path), logger)
        
        # 准备DB路径
        if vector_db_path:
            vector_db_path = Path(vector_db_path)
        else:
            project_root = get_project_root()
            vector_db_path = project_root / "src" / "utils" / "rag" / "tagrag" / "vector_db"
        os.makedirs(vector_db_path, exist_ok=True)
        db_path = str(vector_db_path)
        
        table_name = to_pinyin(topic_name)
        log_success(logger, f"使用表名: {table_name}", "Tagvectorize")
        
        db = lancedb.connect(db_path)
        
        # 重建处理
        if rebuild and table_name in db.table_names():
            db.drop_table(table_name)
            log_success(logger, f"已删除旧表: {table_name}", "Tagvectorize")

        # 获取已存在的ID
        existing_ids = set()
        if not rebuild:
             existing_ids = get_existing_ids(db_path, table_name, logger)
        
        # 筛选新数据
        new_items = []
        for i, item in enumerate(data):
            item_id = item.get('id', i)
            if item_id not in existing_ids:
                new_items.append((item_id, item))
        
        if not new_items:
            log_success(logger, "没有新数据需要处理", "Tagvectorize")
            if table_name in db.table_names():
                return db.open_table(table_name)
            return None

        log_success(logger, f"待处理数据量: {len(new_items)} 条", "Tagvectorize")

        # 批量处理
        total_processed = 0
        table = None
        all_records = []
        
        for i in range(0, len(new_items), batch_size):
            batch_items = new_items[i : i + batch_size]
            batch_texts = [item['tag'] for _, item in batch_items]
            
            # 批量获取向量
            # DashScope API limit is 10 items per batch
            batch_embeddings = get_embeddings_batched(
                batch_texts, client, logger, dimension, model, batch_size=10
            )
            
            # 组装记录
            for (item_id, item), tag_vec in zip(batch_items, batch_embeddings):
                # Ensure ID is string to avoid type conflicts
                record_id = str(item_id)
                
                record = {
                    'id': record_id,
                    'text': item['text'],
                    'tag_vec': tag_vec,
                }
                
                # Handle metadata: convert to JSON string to avoid schema conflicts (struct vs null vs different fields)
                if 'metadata' in item:
                    meta = item['metadata']
                    if isinstance(meta, dict):
                        record['metadata'] = json.dumps(meta, ensure_ascii=False)
                    else:
                        record['metadata'] = str(meta)
                        
                all_records.append(record)
            
            total_processed += len(batch_items)
            log_success(logger, f"已处理(暂存内存): {total_processed}/{len(new_items)}", "Tagvectorize")

        # 一次性写入数据库
        if all_records:
            import pyarrow as pa
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("tag_vec", pa.list_(pa.float64(), dimension)),
                pa.field("metadata", pa.string())
            ])
            
            if table_name in db.table_names():
                table = db.open_table(table_name)
                table.add(all_records)
                log_success(logger, f"追加写入完成: {len(all_records)}条", "Tagvectorize")
            else:
                table = db.create_table(table_name, all_records, schema=schema)
                log_success(logger, f"新建表写入完成: {len(all_records)}条", "Tagvectorize")

        return table
        
    except Exception as e:
        log_error(logger, f"向量化处理失败: {e}", "Tagvectorize")
        raise