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

Performance
-----------

pqfilt applies filters in Arrow C++ *before* converting to a pandas
DataFrame, so rows that would be discarded are never materialised.
When a file has multiple row groups and the filter is on a sorted or
clustered column, pyarrow can skip entire row groups without reading
them — giving much larger speedups.

Benchmark 1 — SPHEREx source catalog (single row group)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Real 3.6M-row SPHEREx catalog (``srccat_2026W07``, 1 row group, 315 MB,
32 columns, warm OS page cache)::

    filter = "ra is not null & dec > -55 & (WISE_W1 > 0 | mag_det1 < 19.5)"

    # pqfilt
    df = pqfilt.read(path, filters=filter)
    df = pqfilt.read(path, filters=filter, columns=["ra", "dec", "WISE_W1", "mag_det1"])

    # pandas equivalent
    df = pd.read_parquet(path)
    df = df[df["ra"].notna() & (df["dec"] > -55) & ((df["WISE_W1"] > 0) | (df["mag_det1"] < 19.5))]

Results (median of 7 runs, 529,760 / 3,619,247 rows = 14.6% kept)::

                                      pandas   pqfilt  speedup
    all 32 columns
      load + filter (total)          191.8 ms  107.3 ms   1.8×

    4 columns (projection)
      load + filter (total)           42.5 ms   18.7 ms   2.3×

With a single row group the gain comes from skipping pandas
materialisation of discarded rows.  Adding ``columns=`` further reduces
I/O and conversion work.

Benchmark 2 — multi-file glob (file skipping)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Real SPHEREx-SSO ephemeris database: 111 ``.parq`` files, 139M rows,
22 columns, warm OS page cache.  Each file covers a distinct
observation window; filtering by Julian Date lets pyarrow skip files
whose ``jd_tdb`` range does not overlap the query::

    filter = "jd_tdb > 2460820 & jd_tdb < 2460830"   # 10-day window → 4 of 111 files

Results (3,926,822 / 139,146,431 rows = 2.8% kept)::

                              pandas                 pqfilt  speedup
    read all + filter in RAM  15,403 ms (11.3 + 4.1 s)  64 ms   240×

pyarrow reads each file's footer statistics and skips the 107 files
whose ``jd_tdb`` range lies entirely outside the query window, reading
only the 4 matching files.

When to expect which speedup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **~2×** — single-file, single row group; gain is from avoiding pandas
  materialisation of filtered-out rows.
* **~10–100×** — many row groups in one file with the filter column
  sorted or clustered.
* **100×+** — multi-file dataset where the filter can exclude entire
  files based on their per-file min/max statistics.

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

Word operators (``in``, ``not in``, ``is null``, and ``is not null``) require
whitespace before the operator. This prevents an unquoted column name ending
in ``in`` from being interpreted as an operator. Symbolic operators do not
have this requirement::

    df = pqfilt.read("data.parquet", filters="spin > 3")
    df = pqfilt.read("data.parquet", filters="margin in 1,2")

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
