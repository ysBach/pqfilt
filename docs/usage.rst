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

Negation
~~~~~~~~

Prefix any sub-expression with ``~`` to negate it.  ``~`` binds tighter than
``&``/``|``, so use parentheses to negate a compound expression::

    # rows where a is NOT greater than 5
    df = pqfilt.read("data.parquet", filters="~(a > 5)")

    # AND with a negated membership test
    df = pqfilt.read("data.parquet", filters="a > 5 & ~(b in 1,2)")

    # negate an OR
    df = pqfilt.read("data.parquet", filters="~(a <= 2 | a >= 9)")

Null Checks
~~~~~~~~~~~

Use ``is null`` and ``is not null`` to filter rows by the presence or absence
of a value.  These operators take no right-hand value::

    df = pqfilt.read("data.parquet", filters="v is null")
    df = pqfilt.read("data.parquet", filters="v is not null")

    # combined with other conditions
    df = pqfilt.read("data.parquet", filters="a > 5 & b is null")

Tuple syntax accepts ``None`` as the value::

    df = pqfilt.read("data.parquet", filters=[("v", "is null", None)])
    df = pqfilt.read("data.parquet", filters=[("v", "is not null", None)])

Boolean Columns
~~~~~~~~~~~~~~~

Boolean literals ``True`` / ``False`` (any capitalisation) are recognised
and converted to Python ``bool`` before being passed to PyArrow, avoiding
type-mismatch errors during predicate pushdown::

    df = pqfilt.read("data.parquet", filters="is_comet == True")
    df = pqfilt.read("data.parquet", filters="is_comet == false")
    df = pqfilt.read("data.parquet", filters="is_comet != TRUE")

Membership Filters
~~~~~~~~~~~~~~~~~~

Use ``in`` and ``not in`` with comma-separated values. You can optionally enclose the
list in brackets ``[]`` or parentheses ``()`` for readability::

    df = pqfilt.read("data.parquet", filters="desig in [1, 2, 3]")
    df = pqfilt.read("data.parquet", filters="name not in (foo, bar)")
    df = pqfilt.read("data.parquet", filters="desig in '1', '2', '3'")

If your Parquet column is a string type but contains numeric-looking values
(like ``"1"``), explicitly wrap the values in single or double quotes to
prevent `pqfilt` from coercing them to numbers. This avoids PyArrow type errors::

    # '1' is preserved as a string
    df = pqfilt.read("data.parquet", filters="desig in ['1', '356']")

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

Filtering a Loaded DataFrame
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use :func:`pqfilt.filter_df` to apply the same expression syntax to a
DataFrame already in memory::

    import pandas as pd
    import pqfilt

    df = pd.read_csv("data.csv")  # or any other source

    out = pqfilt.filter_df(df, "a > 5 & b < 80")
    out = pqfilt.filter_df(df, "~(a in 1,2,3)")
    out = pqfilt.filter_df(df, "v is not null")

All operators, boolean literals, backtick-quoted column names, and tuple/DNF
syntax work identically to :func:`pqfilt.read`.

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
