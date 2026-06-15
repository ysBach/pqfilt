Changelog
=========

v0.2.1 (2026-06-15)
--------------------

* Exported ``to_pyarrow_expr`` in the public API (previously internal).

v0.2.0 (2026-06-15)
--------------------

* **Breaking**: removed ``per_file`` parameter from ``read()``.
* Added ``is null`` / ``is not null`` operators.
* Added ``~`` prefix negation (``NotExpr``).
* Fixed quoted literals (``'a|b'``, ``'a&b'``, etc.) being split on structural characters.
* Fixed ``in``/``not in`` list items with commas inside quotes (``desig in 'a,b', 'c'``).
* Fixed boolean column filtering: ``True``/``False`` strings now coerce to ``bool`` before pyarrow pushdown.
* Multi-file reads now use a single ``ds.dataset(files)`` call (parallel I/O).
* Parquet output now uses ``pq.write_table`` to preserve Arrow type fidelity.
* Added ``filter_df(df, filters)`` to apply the same filter syntax to an already-loaded DataFrame.

v0.1.6 (2026-04-29)
--------------------

* ``True``/``False`` string literals (case-insensitive) are now converted to Python ``bool`` before pyarrow, preventing type-mismatch errors on boolean columns.

v0.1.5 (2026-02-23)
--------------------

* list/tuple: ``in``/``not in`` value lists now accept bracket/parenthesis enclosures.
  * ``"desig in [1, 2, 3]"`` and ``"desig in (1, 2, 3)"`` work in addition to
  the bare comma-separated form.
* Bugfix a few edge cases.


v0.1.4 (2026-02-23)
--------------------

* Similar fix as 0.1.3: Fixed ``in``/``not in`` value parsing
  * ``"desig in '356', '3200'"`` are preserved as strings.

v0.1.3 (2026-02-23)
--------------------

* Fixed quoted scalar values
  * ``"name == '42'"`` now correctly preserves ``'42'`` as a string instead of coercing it to the integer ``42``.

v0.1.2 (2026-02-21)
--------------------

* version bump only.

v0.1.1 (2026-02-21)
--------------------

* Added Python 3.9 support.
* Fixed Sphinx documentation build warnings.

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
