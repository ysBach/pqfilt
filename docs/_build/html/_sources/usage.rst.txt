Usage Guide
===========

Installation
------------

From PyPI (once published)::

    pip install pqfilt

From source::

    git clone https://github.com/ysBach/pqfilt.git
    cd pqfilt
    pip install -e .

Python API
----------

Basic Filtering
~~~~~~~~~~~~~~~

The main entry point is :func:`pqfilt.read`::

    import pqfilt

    # Simple comparison
    df = pqfilt.read("data.parquet", filters="vmag < 20")

    # Equality
    df = pqfilt.read("data.parquet", filters="flag == 1")

Expression Syntax
~~~~~~~~~~~~~~~~~

Expressions support ``&`` (AND), ``|`` (OR), and parentheses for grouping.
``&`` binds tighter than ``|`` (standard boolean precedence)::

    # AND: both conditions must hold
    df = pqfilt.read("data.parquet", filters="a > 5 & b < 10")

    # OR: either condition holds
    df = pqfilt.read("data.parquet", filters="a < 3 | a > 8")

    # Mixed with parentheses
    df = pqfilt.read("data.parquet", filters="(a < 3 & b > 50) | c == 1")

Membership Filters
~~~~~~~~~~~~~~~~~~

Use ``in`` and ``not in`` with comma-separated values::

    df = pqfilt.read("data.parquet", filters="desig in 1,2,3")
    df = pqfilt.read("data.parquet", filters="name not in foo,bar")

Tuple Syntax
~~~~~~~~~~~~

For programmatic use, pass filters as a list of 3-tuples (flat AND)::

    df = pqfilt.read("data.parquet", filters=[("a", ">", 5), ("b", "<", 10)])

Or as a list of lists for DNF (OR of AND-groups)::

    df = pqfilt.read("data.parquet", filters=[
        [("a", "<", 3)],
        [("a", ">", 8)],
    ])

Column Selection
~~~~~~~~~~~~~~~~

Use ``columns`` for projection pushdown (only listed columns are read)::

    df = pqfilt.read("data.parquet", filters="a > 5", columns=["a", "b"])

Special Column Names
~~~~~~~~~~~~~~~~~~~~

Columns with spaces, hyphens, or operator characters can be
backtick-quoted::

    df = pqfilt.read("data.parquet", filters="`alpha*360` > 100")
    df = pqfilt.read("data.parquet", filters="`my column` <= 50")

Multi-file and Glob
~~~~~~~~~~~~~~~~~~~

Pass a glob pattern or a list of files::

    df = pqfilt.read("data/*.parquet", filters="vmag < 20")
    df = pqfilt.read(["file1.parquet", "file2.parquet"], filters="a > 5")

Output
~~~~~~

Save filtered results directly::

    df = pqfilt.read("data.parquet", filters="a > 5", output="out.parquet")
    df = pqfilt.read("data.parquet", filters="a > 5", output="out.csv")

CLI Usage
---------

Basic usage::

    pqfilt data/*.parquet -f "vmag < 20" -o filtered.parquet

Multiple ``-f`` flags are AND-ed together::

    pqfilt data/*.parquet -f "vmag < 20" -f "dec > 30" -o filtered.parquet

Boolean expressions within a single ``-f``::

    pqfilt data/*.parquet -f "(a < 30 & b > 50) | c == 1" -o out.parquet

Column selection::

    pqfilt data/*.parquet -f "vmag < 20" --columns vmag,ra,dec -o out.parquet

Overwrite existing output::

    pqfilt data/*.parquet -f "vmag < 20" -o out.parquet --overwrite
