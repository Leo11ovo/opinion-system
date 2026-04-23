import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from .chunker import ExpertChunker

try:
    import fitz  # type: ignore
except Exception:
    fitz = None

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None


def _safe_name(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _read_docx_text(file_path: Path) -> str:
    try:
        import docx  # type: ignore
    except Exception:
        return ""
    try:
        doc = docx.Document(str(file_path))
        return "\n".join(p.text for p in doc.paragraphs if str(p.text).strip())
    except Exception:
        return ""


def _read_generic_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return PDFParser.parse(file_path)
    if suffix == ".docx":
        return _read_docx_text(file_path)
    try:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_paper_keywords(content: str, limit: int = 8) -> List[str]:
    # Capture "关键词/Keywords" line first, then fallback to frequent terms.
    kw_match = re.search(r"(关键词|关键字|Keywords?)\s*[:：]\s*(.+)", content, re.IGNORECASE)
    candidates: List[str] = []
    if kw_match:
        raw = kw_match.group(2).strip()
        parts = re.split(r"[;；,，/|]", raw)
        candidates = [p.strip() for p in parts if 1 < len(p.strip()) < 40]
    if candidates:
        return candidates[:limit]

    # Lightweight fallback term extraction (Chinese/English phrases)
    terms = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z\-]{3,20}", content[:12000])
    stop = {"我们", "研究", "分析", "以及", "进行", "通过", "结果", "方法", "模型", "论文", "文章"}
    freq: Dict[str, int] = {}
    for term in terms:
        t = term.strip()
        if not t or t in stop:
            continue
        freq[t] = freq.get(t, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in ranked[:limit]]

class PDFParser:
    """Helper class to parse PDF files."""
    @staticmethod
    def parse(file_path: Path) -> str:
        text = ""
        if fitz is not None:
            try:
                with fitz.open(file_path) as doc:
                    for page in doc:
                        text += page.get_text()
                return text
            except Exception as e:
                print(f"Error reading PDF via fitz {file_path}: {e}")

        if PdfReader is not None:
            try:
                reader = PdfReader(str(file_path))
                for page in reader.pages:
                    text += (page.extract_text() or "")
                return text
            except Exception as e:
                print(f"Error reading PDF via pypdf {file_path}: {e}")
        return text

    @staticmethod
    def extract_metadata(file_path: Path) -> Dict:
        metadata = {}
        if fitz is not None:
            try:
                with fitz.open(file_path) as doc:
                    metadata = doc.metadata or {}
                return metadata
            except Exception:
                pass
        if PdfReader is not None:
            try:
                reader = PdfReader(str(file_path))
                md = reader.metadata or {}
                metadata = {"title": str(getattr(md, "title", "") or md.get("/Title", ""))}
            except Exception:
                pass
        return metadata

class PromptParser:
    """Parses files from '分析角度框架prompt/'."""
    @staticmethod
    def parse(file_path: Path) -> Tuple[Dict, List[Dict], List[Dict]]:
        content = file_path.read_text(encoding='utf-8')
        name = file_path.stem.replace("_", " ").title()
        
        # Method Node (Root)
        doc_node = {
            "id": f"method_{file_path.stem}",
            "label": "Method",
            "name": name,
            "description": content[:500],
            "source_pdf": str(file_path.name)
        }
        
        entities = []
        relationships = []
        
        # 1. Extract Indicators (e.g., "- 关注度: ...")
        # Regex for common bullet points in prompt files
        indicator_pattern = r"[-*]\s*(.*?)[：:]\s*(.*?)\n"
        for match in re.finditer(indicator_pattern, content):
            ind_name = match.group(1).strip()
            ind_desc = match.group(2).strip()
            
            # Filter out noise (too short/long)
            if len(ind_name) < 2 or len(ind_name) > 50: continue
            
            ind_id = f"ind_{file_path.stem}_{ind_name}"
            entities.append({
                "id": ind_id,
                "label": "Indicator",
                "name": ind_name,
                "description": ind_desc,
                "source_pdf": str(file_path.name)
            })
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": ind_id,
                "type": "HAS_INDICATOR"
            })

        # 2. Chunking (Context)
        chunker = ExpertChunker()
        chunk_nodes = chunker.chunk_text(content, doc_node["id"])
        
        # Link doc to chunks
        for chunk in chunk_nodes:
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": chunk["id"],
                "type": "HAS_CHUNK"
            })
            
        # Link chunks sequentially
        for i in range(len(chunk_nodes) - 1):
            relationships.append({
                "source_id": chunk_nodes[i]["id"],
                "target_id": chunk_nodes[i+1]["id"],
                "type": "NEXT_CHUNK"
            })
            
        # Combine entities and chunks into the second return value
        all_nodes = entities + chunk_nodes
            
        return doc_node, all_nodes, relationships

class CaseParser:
    """Parses files from '舆情事件库/' based on template."""
    @staticmethod
    def parse(file_path: Path) -> Tuple[Dict, List[Dict], List[Dict]]:
        content = file_path.read_text(encoding='utf-8')
        all_nodes = [] 
        relationships = []
        
        # 1. Metadata (CaseStudy Node)
        case_id_match = re.search(r"- 案例编号.*?：(.*?)\n", content)
        case_title_match = re.search(r"- 案例名称.*?：(.*?)\n", content)
        summary_match = re.search(r"- 一句话摘要.*?：(.*?)\n", content)
        
        cid = case_id_match.group(1).strip() if case_id_match else file_path.stem
        ctitle = case_title_match.group(1).strip() if case_title_match else file_path.stem
        csummary = summary_match.group(1).strip() if summary_match else ""
        
        case_node = {
            "id": cid,
            "label": "CaseStudy",
            "name": ctitle,
            "description": csummary,
            "source_pdf": str(file_path.name)
        }
        
        # 2. Actors (Stakeholder Nodes)
        actor_pattern = r"\|\s*(actor_\w+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*.*?\|\s*(.*?)\s*\|"
        for match in re.finditer(actor_pattern, content):
            aid, aname, atype, roles = match.groups()
            if "主体名称" in aname: continue # Skip header
            
            aname = aname.split("（")[0].split("(")[0].strip() # Clean name
            
            all_nodes.append({
                "id": aid.strip(),
                "label": "Stakeholder",
                "name": aname,
                "description": f"Type: {atype.strip()}",
                "source_pdf": str(file_path.name)
            })
            relationships.append({
                "source_id": aid.strip(),
                "target_id": cid,
                "type": "INVOLVED_IN",
                "roles": roles.strip()
            })

        # 3. Key Milestones (Event Nodes)
        milestone_pattern = r"#### (T\d+.*?)\n- 时间.*?：(.*?)\n- 节点描述.*?：(.*?)\n"
        for match in re.finditer(milestone_pattern, content, re.DOTALL):
            tid, ttime, tdesc = match.groups()
            eid = f"{cid}_{tid.split('（')[0].strip()}"
            
            all_nodes.append({
                "id": eid,
                "label": "Event",
                "name": f"{ctitle} - {tid.strip()}",
                "description": f"[{ttime.strip()}] {tdesc.strip()}",
                "source_pdf": str(file_path.name)
            })
            relationships.append({
                "source_id": cid,
                "target_id": eid,
                "type": "HAS_EVENT"
            })

        # 4. Risk Types (Risk Nodes)
        risk_pattern = r"- \[x\] (.*?风险.*?)\n"
        for match in re.finditer(risk_pattern, content):
            risk_name = match.group(1).split("（")[0].strip()
            rid = f"risk_{risk_name}"
            
            all_nodes.append({
                "id": rid,
                "label": "Risk",
                "name": risk_name,
                "description": "Standard Risk Type"
            })
            relationships.append({
                "source_id": cid,
                "target_id": rid,
                "type": "HAS_RISK"
            })

        # 5. Insights (Guideline Nodes)
        insight_pattern = r"- Insight \d+.*?\n\s*- 洞见表述.*?：(.*?)\n"
        for i, match in enumerate(re.finditer(insight_pattern, content)):
            desc = match.group(1).strip()
            gid = f"{cid}_insight_{i+1}"
            
            all_nodes.append({
                "id": gid,
                "label": "Guideline",
                "name": f"Insight from {ctitle}",
                "description": desc,
                "source_pdf": str(file_path.name)
            })
            relationships.append({
                "source_id": cid,
                "target_id": gid,
                "type": "YIELDS_INSIGHT"
            })

        # 6. Chunking (Context)
        chunker = ExpertChunker()
        chunks = chunker.chunk_text(content, cid)
        all_nodes.extend(chunks)
        
        for chunk in chunks:
            relationships.append({
                "source_id": cid,
                "target_id": chunk["id"],
                "type": "HAS_CHUNK"
            })

        return case_node, all_nodes, relationships

class ReportParser:
    """Parses files from '智库报告及深度分析' and '舆情分析报告'."""
    @staticmethod
    def parse(file_path: Path) -> Tuple[Dict, List[Dict], List[Dict]]:
        content = _read_generic_text(file_path)
        name = file_path.stem
        if file_path.suffix.lower() == ".pdf":
            meta = PDFParser.extract_metadata(file_path)
            name = _safe_name(meta.get("title"), file_path.stem)
        elif content.strip():
            lines = content.split("\n")
            if lines and lines[0].strip():
                name = lines[0].strip().replace("#", "").strip()

        if not content.strip():
            return {}, [], []

        doc_node = {
            "id": f"report_{file_path.stem}",
            "label": "Report",
            "name": name,
            "description": content[:1000],
            "source_pdf": str(file_path.name),
            "full_content": content 
        }
        
        # Future: Extract entities using LLM here
        
        chunker = ExpertChunker()
        chunk_nodes = chunker.chunk_text(content, doc_node["id"])
        
        relationships = []
        for chunk in chunk_nodes:
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": chunk["id"],
                "type": "HAS_CHUNK"
            })
            
        for i in range(len(chunk_nodes) - 1):
            relationships.append({
                "source_id": chunk_nodes[i]["id"],
                "target_id": chunk_nodes[i+1]["id"],
                "type": "NEXT_CHUNK"
            })
            
        return doc_node, chunk_nodes, relationships

class ResearchPaperParser:
    """Parses files from '研究文章'."""
    @staticmethod
    def parse(file_path: Path, category: str = "") -> Tuple[Dict, List[Dict], List[Dict]]:
        content = _read_generic_text(file_path)
        name = file_path.stem
        if file_path.suffix.lower() == ".pdf":
            meta = PDFParser.extract_metadata(file_path)
            name = _safe_name(meta.get("title"), file_path.stem)
        else:
            name = _safe_name(file_path.stem, file_path.name)

        if not content.strip():
            return {}, [], []

        paper_id = f"paper_{category}_{file_path.stem}" if category else f"paper_{file_path.stem}"
        doc_node = {
            "id": paper_id,
            "label": "ResearchPaper",
            "name": name,
            "description": content[:1000],
            "source_pdf": str(file_path.name),
            "category": category
        }
        
        chunker = ExpertChunker()
        chunk_nodes = chunker.chunk_text(content, doc_node["id"])
        
        relationships: List[Dict] = []
        for chunk in chunk_nodes:
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": chunk["id"],
                "type": "HAS_CHUNK"
            })
            
        for i in range(len(chunk_nodes) - 1):
            relationships.append({
                "source_id": chunk_nodes[i]["id"],
                "target_id": chunk_nodes[i+1]["id"],
                "type": "NEXT_CHUNK"
            })

        # Lightweight entity extraction for papers: category + keywords -> Indicator nodes
        entity_nodes: List[Dict] = []
        if category:
            category_id = f"ind_{doc_node['id']}_category"
            entity_nodes.append({
                "id": category_id,
                "label": "Indicator",
                "name": category,
                "description": f"论文分类: {category}",
                "source_pdf": str(file_path.name),
            })
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": category_id,
                "type": "HAS_INDICATOR",
            })

        for idx, kw in enumerate(_extract_paper_keywords(content), 1):
            kid = f"ind_{doc_node['id']}_kw_{idx}"
            entity_nodes.append({
                "id": kid,
                "label": "Indicator",
                "name": kw,
                "description": f"论文关键词: {kw}",
                "source_pdf": str(file_path.name),
            })
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": kid,
                "type": "HAS_INDICATOR",
            })

        return doc_node, chunk_nodes + entity_nodes, relationships

class MethodologyParser:
    """Parses files from '舆情分析方法论'."""
    @staticmethod
    def parse(file_path: Path) -> Tuple[Dict, List[Dict], List[Dict]]:
        content = _read_generic_text(file_path)
        
        if not content.strip():
            return {}, [], []

        # Identify if it's a Theory or generic Methodology
        label = "Methodology"
        if "理论" in file_path.stem or "Theory" in file_path.stem:
            label = "Theory"
        elif "指南" in file_path.stem or "Guideline" in file_path.stem:
            label = "Guideline"

        doc_node = {
            "id": f"methodology_{file_path.stem}",
            "label": label,
            "name": file_path.stem,
            "description": content[:1000],
            "source_pdf": str(file_path.name)
        }
        
        chunker = ExpertChunker()
        chunk_nodes = chunker.chunk_text(content, doc_node["id"])
        
        relationships = []
        for chunk in chunk_nodes:
            relationships.append({
                "source_id": doc_node["id"],
                "target_id": chunk["id"],
                "type": "HAS_CHUNK"
            })
            
        for i in range(len(chunk_nodes) - 1):
            relationships.append({
                "source_id": chunk_nodes[i]["id"],
                "target_id": chunk_nodes[i+1]["id"],
                "type": "NEXT_CHUNK"
            })
            
        return doc_node, chunk_nodes, relationships
