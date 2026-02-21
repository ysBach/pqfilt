# pqfilt

Generic Parquet filtering tool (CLI and Python API).

[ReadtheDocs Documentation](https://pqfilt.readthedocs.io/en/latest/).

Originally developed while dealing with large Parquet files in [SPHEREx mission](https://spherex.caltech.edu/) ([GitHub](https://github.com/SPHEREx)).

`pqfilt` wraps `pyarrow.dataset` to let you filter Parquet files **before** they
are fully read into memory, using row-group-level filtering.

## Installation

```bash
pip install pqfilt
# or
uv add pqfilt
```

## Python API

```python
import pqfilt

# Simple filter
df = pqfilt.read("data.parquet", filters="vmag < 20")

# AND + OR with expression syntax
df = pqfilt.read("data.parquet", filters="(a < 30 & b > 50) | c == 1")

# Tuple syntax (flat AND)
df = pqfilt.read("data.parquet", filters=[("a", "<", 30), ("b", ">", 50)])

# DNF syntax (OR of ANDs)
df = pqfilt.read("data.parquet", filters=[
    [("a", "<", 30)],
    [("b", ">", 50)],
])

# Column selection + output
df = pqfilt.read("data/*.parquet", columns=["a", "b"], output="out.parquet")
```

## CLI

```bash
# Basic filter
pqfilt data/*.parquet -f "vmag < 20" -o filtered.parquet

# AND + OR expression
pqfilt data/*.parquet -f "(a < 30 & b > 50) | c == 1" -o filtered.parquet

# Multiple -f flags (AND-ed together)
pqfilt data/*.parquet -f "vmag < 20" -f "dec > 30" -o filtered.parquet

# Column selection
pqfilt data/*.parquet -f "vmag < 20" --columns vmag,ra,dec -o filtered.parquet

# Membership filter
pqfilt data/*.parquet -f "desig in 1,2,3" -o filtered.parquet
```

### Column names with special characters

Columns containing operator characters can be backtick-quoted:

```python
pqfilt.read("data.parquet", filters="`alpha*360` > 100")
```

## License

MIT
