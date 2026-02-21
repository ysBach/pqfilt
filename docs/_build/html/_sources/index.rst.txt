pqfilt
======

Generic Parquet predicate-pushdown filter tool -- CLI and Python API.

``pqfilt`` wraps ``pyarrow.dataset`` to let you filter Parquet files
**before** they are fully read into memory, using row-group-level
predicate pushdown.

Quick Start
-----------

Python API::

    import pqfilt

    # Simple filter
    df = pqfilt.read("data.parquet", filters="vmag < 20")

    # AND + OR with expression syntax
    df = pqfilt.read("data.parquet", filters="(a < 30 & b > 50) | c == 1")

    # Tuple syntax (flat AND)
    df = pqfilt.read("data.parquet", filters=[("a", "<", 30), ("b", ">", 50)])

CLI::

    pqfilt data/*.parquet -f "vmag < 20" -o filtered.parquet
    pqfilt data/*.parquet -f "(a < 30 & b > 50) | c == 1" -o out.parquet

.. toctree::
   :maxdepth: 2
   :caption: Contents

   usage
   api
   changelog
