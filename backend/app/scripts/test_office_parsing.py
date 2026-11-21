from io import BytesIO

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from app.services.parsing.document_parser import (
    parse_document,
)

from pathlib import Path

def create_docx_data() -> bytes:
    document = Document()
    document.add_heading("RAG Notebook Word 测试", level=1)
    document.add_paragraph(
        "Milvus 用于保存文档分块的向量。"
    )

    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "组件"
    table.cell(0, 1).text = "作用"
    table.cell(1, 0).text = "PostgreSQL"
    table.cell(1, 1).text = "保存业务数据"

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def create_pptx_data() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(
        presentation.slide_layouts[5]
    )

    if slide.shapes.title is not None:
        slide.shapes.title.text = "RAG Notebook PPT 测试"

    text_box = slide.shapes.add_textbox(
        Inches(1),
        Inches(2),
        Inches(8),
        Inches(1),
    )

    text_box.text_frame.text = (
        "BGE-M3 用于生成稠密向量和稀疏向量。"
    )

    table_shape = slide.shapes.add_table(
        2,
        2,
        Inches(1),
        Inches(3),
        Inches(8),
        Inches(1.5),
    )

    table = table_shape.table
    table.cell(0, 0).text = "检索方式"
    table.cell(0, 1).text = "说明"
    table.cell(1, 0).text = "Hybrid"
    table.cell(1, 1).text = "融合语义检索与关键词检索"

    buffer = BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def create_xlsx_data() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "技术组件"

    worksheet.append(["组件", "作用"])
    worksheet.append(["Redis", "Celery 消息代理"])
    worksheet.append(["MinIO", "保存原始文档"])
    worksheet.append(["Milvus", "保存文档向量"])

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def check_parser(
    file_name: str,
    file_data: bytes,
    expected_parser: str,
    expected_text: str,
) -> None:
    parsed_units, parser_name = parse_document(
        file_name,
        file_data,
    )

    assert parser_name == expected_parser
    assert parsed_units

    all_text = "\n".join(
        unit.text
        for unit in parsed_units
    )

    assert expected_text in all_text

    print(
        f"{file_name}: "
        f"parser={parser_name}, "
        f"units={len(parsed_units)}, "
        f"characters={len(all_text)}"
    )


def main() -> None:
    sample_dir = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "office"
    )

    sample_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    docx_data = create_docx_data()
    pptx_data = create_pptx_data()
    xlsx_data = create_xlsx_data()

    (sample_dir / "office-test.docx").write_bytes(
        docx_data
    )

    (sample_dir / "office-test.pptx").write_bytes(
        pptx_data
    )

    (sample_dir / "office-test.xlsx").write_bytes(
        xlsx_data
    )

    check_parser(
        "office-test.docx",
        docx_data,
        "python-docx",
        "PostgreSQL",
    )

    check_parser(
        "office-test.pptx",
        pptx_data,
        "python-pptx",
        "BGE-M3",
    )

    check_parser(
        "office-test.xlsx",
        xlsx_data,
        "openpyxl",
        "MinIO",
    )

    print("DOCX、PPTX、XLSX 解析测试全部通过")
    print(f"测试文件已保存到：{sample_dir}")


if __name__ == "__main__":
    main()
