Advanced API
============

This page is for Arrow-native workflows and applications that need to rewrite
filter expressions for a storage schema. For routine filtering, use the
:doc:`usage` guide instead.

Arrow Scanners
--------------

Use :func:`pqfilt.scan` to obtain a lazily evaluated
``pyarrow.dataset.Scanner``. It applies the same source resolution, filter
syntax, and projection behavior as :func:`pqfilt.read`, but lets the caller
choose how to consume the data::

    scanner = pqfilt.scan("data.parquet", filters="vmag < 20")
    table = scanner.to_table()

    # Or process batches without materializing a table.
    for batch in pqfilt.scan("data.parquet", filters="vmag < 20").to_batches():
        process(batch)

The scanner exposes ``dataset_schema`` for the stored schema and
``projected_schema`` for the requested output projection.

Streaming Writes
----------------

Use :func:`pqfilt.write_filtered` when the filtered result only needs to be
saved. It scans and writes record batches without materializing the complete
result in memory, and returns the number of rows written::

    rows_written = pqfilt.write_filtered(
        "data/*.parquet",
        "filtered.parquet",
        filters="vmag < 20",
    )

Parquet is written by default; a ``.csv`` output path selects CSV. The output
path must not be an input file.

AST Transformations
-------------------

Use :func:`pqfilt.to_ast` to normalize an expression string, tuple filters,
DNF filters, or an existing AST. Then use :func:`pqfilt.map_leaves` to rewrite
each comparison. A callback may replace one leaf with a compound expression
when a storage schema requires it::

    ast = pqfilt.to_ast("magnitude < 20")

    def rename_column(leaf):
        return pqfilt.FilterExpr(f"stored_{leaf.col}", leaf.op, leaf.val)

    rewritten = pqfilt.map_leaves(ast, rename_column)
    arrow_filter = pqfilt.to_pyarrow_expr(rewritten)

Operator API
------------

The supported operators and their validation helper are public for callers
that build tuple filters programmatically::

    pqfilt.validate_operator("in")
    operators = pqfilt.SUPPORTED_OPERATORS

For complete signatures and AST node definitions, see the :doc:`api` reference.
