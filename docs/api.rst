API Reference
=============

.. module:: pqfilt

Core
----

.. autofunction:: pqfilt.read

.. autofunction:: pqfilt.scan

.. autofunction:: pqfilt.write_filtered

.. autofunction:: pqfilt.filter_df

.. autofunction:: pqfilt.to_ast

Operators
---------

.. autodata:: pqfilt.SUPPORTED_OPERATORS

.. autofunction:: pqfilt.validate_operator

Expression Parser
-----------------

.. autofunction:: pqfilt.parse_expression

.. autofunction:: pqfilt.map_leaves

.. autofunction:: pqfilt.to_pyarrow_expr

AST Nodes
~~~~~~~~~

.. autoclass:: pqfilt.FilterExpr

.. autoclass:: pqfilt.AndExpr

.. autoclass:: pqfilt.OrExpr

.. autoclass:: pqfilt.NotExpr
