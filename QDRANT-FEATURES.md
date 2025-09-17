# How VIA Leverages Qdrant's Advanced Features

VeriStamp Incident Atlas (VIA) was designed from the ground up to showcase the power of Qdrant as a core operational database for observability, moving far beyond typical AI-driven RAG applications. This document details the specific, advanced features of Qdrant that make VIA's real-time, scalable architecture possible.

## 1. Advanced Search & Retrieval APIs

VIA uses Qdrant's sophisticated search APIs to build intelligent, user-facing features that provide immediate value.

### Grouping API for Automated Incident Clustering
- **Qdrant Feature:** `client.search_groups` with the `group_by` parameter.
- **How VIA Uses It:** To prevent overwhelming operators with thousands of similar log entries, VIA uses the Grouping API to perform incident aggregation directly within the database. By specifying `group_by="rhythm_hash"`, the backend retrieves only the top-scoring representative for each unique incident type, providing a clean, deduplicated view of active issues in the "Radar" and "Atlas" UIs.

### Recommendation API for Advanced Triage
- **Qdrant Feature:** `client.recommend` with positive and negative examples.
- **How VIA Uses It:** The Triage Engine is powered by Qdrant's Recommendation API, which allows for a highly surgical root cause analysis. The UI allows an operator to mark events as "relevant" (positive) or "irrelevant" (negative). These lists of IDs are passed directly to the `recommend` function, which finds results that are semantically close to the positive examples while being far from the negative ones.

### Hybrid Search for Precision
- **Qdrant Feature:** Combination of dense vectors, sparse vectors, and full-text search filters.
- **How VIA Uses It:** The "Atlas" UI allows for complex queries that combine multiple search methods. A single query can leverage a dense vector for semantic meaning, a sparse BM25 vector for keyword relevance, and a `MatchText` filter for exact phrase matching. This is enabled by VIA's multi-vector setup in the Tier 2 collections.

---
## 2. Scalability & Performance Architecture

VIA is built to handle massive, time-series data streams by leveraging Qdrant's production-grade scalability and performance features.

### On-Disk Storage for Massive Scale
- **Qdrant Feature:** `on_disk=True` vector parameter.
- **How VIA Uses It:** The Tier 2 Forensic Index is designed for long-term data retention. To make this cost-effective, all dense vectors in Tier 2 collections are configured with `on_disk=True`. This allows the vector index to be far larger than the available RAM, enabling VIA to manage terabytes of historical data on modest hardware.

### Vector Quantization for Efficiency (Binary & Scalar)
- **Qdrant Feature:** `BinaryQuantization` and `ScalarQuantization`.
- **How VIA Uses It:** VIA uses two different types of quantization to optimize for its two-tiered architecture:
    - **Binary Quantization**: The high-throughput Tier 1 monitor uses binary quantization to convert its 64-dimensional vectors into tiny 64-bit fingerprints stored entirely in RAM (`always_ram=True`) for extreme speed.
    - **Scalar Quantization**: The Tier 2 index uses scalar quantization to compress its larger dense vectors into 8-bit integers, drastically reducing their memory and disk footprint while maintaining high search accuracy.

### Time-Partitioned Collections for Time-Series Data
- **Qdrant Feature:** Dynamic collection management.
- **How VIA Uses It:** Instead of a single monolithic index, the Tier 2 Forensic Index is composed of daily collections (e.g., `via_forensic_index_v2_2025_09_17`). This common time-series pattern keeps queries on recent data fast, simplifies data retention policies (old collections can simply be dropped), and is managed automatically by the `QdrantService`.

---
## 3. Advanced Data Modeling & Indexing

VIA's collections are structured to store rich data and query it with maximum efficiency.

### Multi-Vector Support (Named Vectors)
- **Qdrant Feature:** Using named vectors within a single collection.
- **How VIA Uses It:** Each point in the Tier 2 collections stores multiple vector representations for a single log event: a dense `log_dense_vector` for semantic meaning and a sparse `bm25_vector` for keyword relevance. This is the core data model that enables powerful hybrid search.

### Payload Indexing & Filtering for Speed
- **Qdrant Feature:** `create_payload_index` and the `Filter` object.
- **How VIA Uses It:** To accelerate queries, VIA creates indexes on key payload fields like `service`, `rhythm_hash`, and timestamps (`ts`, `start_ts`). This allows Qdrant to use a `Filter` to rapidly narrow down the search space *before* performing the more computationally expensive vector search, ensuring low latency even on large datasets.

### Scroll API for Efficient Data Retrieval
- **Qdrant Feature:** `client.scroll` API.
- **How VIA Uses It:** When the `RhythmAnalysisService` needs to analyze a recent time window of data from the Tier 1 monitor, it uses the `scroll` API with a `Filter` on the indexed timestamp (`ts`). This is the most efficient method to retrieve all points matching a specific criteria without the overhead of a vector search.