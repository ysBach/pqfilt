Changelog
=========

v0.1.0 (2026-02-21)
--------------------

* Initial release.
* Core ``read()`` function with predicate-pushdown via ``pyarrow.dataset``.
* Expression parser supporting ``&``, ``|``, parentheses, ``in``/``not in``.
* Backtick quoting for column names with special characters.
* Tuple and DNF filter syntax.
* CLI tool (``pqfilt``) with ``-f`` expression option.
* Multi-file and glob support.
* Output to Parquet or CSV.
