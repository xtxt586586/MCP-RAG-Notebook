from pymilvus import DataType, MilvusClient

from app.core.config import settings


DENSE_VECTOR_DIMENSION = 1024


def create_schema():
    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
    )

    schema.add_field(
        field_name="id",
        datatype=DataType.VARCHAR,
        is_primary=True,
        max_length=64,
    )

    schema.add_field(
        field_name="user_id",
        datatype=DataType.VARCHAR,
        max_length=64,
    )

    schema.add_field(
        field_name="knowledge_base_id",
        datatype=DataType.VARCHAR,
        max_length=64,
    )

    schema.add_field(
        field_name="document_id",
        datatype=DataType.VARCHAR,
        max_length=64,
    )

    schema.add_field(
        field_name="chunk_index",
        datatype=DataType.INT64,
    )

    schema.add_field(
        field_name="content",
        datatype=DataType.VARCHAR,
        max_length=65535,
    )

    schema.add_field(
        field_name="source_type",
        datatype=DataType.VARCHAR,
        max_length=32,
    )

    schema.add_field(
        field_name="page_number",
        datatype=DataType.INT64,
    )

    schema.add_field(
        field_name="start_seconds",
        datatype=DataType.FLOAT,
    )

    schema.add_field(
        field_name="end_seconds",
        datatype=DataType.FLOAT,
    )

    schema.add_field(
        field_name="metadata",
        datatype=DataType.JSON,
    )

    schema.add_field(
        field_name="dense_vector",
        datatype=DataType.FLOAT_VECTOR,
        dim=DENSE_VECTOR_DIMENSION,
    )

    schema.add_field(
        field_name="sparse_vector",
        datatype=DataType.SPARSE_FLOAT_VECTOR,
    )

    return schema


def create_indexes():
    index_params = MilvusClient.prepare_index_params()

    index_params.add_index(
        field_name="dense_vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={
            "M": 16,
            "efConstruction": 200,
        },
    )

    index_params.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="IP",
    )

    index_params.add_index(
        field_name="user_id",
        index_type="INVERTED",
    )

    index_params.add_index(
        field_name="knowledge_base_id",
        index_type="INVERTED",
    )

    index_params.add_index(
        field_name="document_id",
        index_type="INVERTED",
    )

    return index_params


def initialize_collection() -> None:
    collection_name = settings.milvus_collection

    client = MilvusClient(uri=settings.milvus_uri)

    try:
        if client.has_collection(collection_name=collection_name):
            print(f"Collection 已存在：{collection_name}")
        else:
            print(f"正在创建 Collection：{collection_name}")

            client.create_collection(
                collection_name=collection_name,
                schema=create_schema(),
                index_params=create_indexes(),
            )

            print(f"Collection 创建成功：{collection_name}")

        client.load_collection(collection_name=collection_name)

        description = client.describe_collection(
            collection_name=collection_name
        )

        print("Collection 加载成功")
        print("Collection 名称：", description["collection_name"])
        print("字段数量：", len(description["fields"]))
        print("当前 Collections：", client.list_collections())

    finally:
        client.close()


if __name__ == "__main__":
    initialize_collection()