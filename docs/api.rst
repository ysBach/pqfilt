API Reference
=============

.. module:: pqfilt

Core
----

.. autofunction:: pqfilt.read

Expression Parser
-----------------

.. autofunction:: pqfilt.parse_expression

.. autofunction:: pqfilt._parser.to_pyarrow_expr

AST Nodes
~~~~~~~~~

.. autoclass:: pqfilt.FilterExpr

.. autoclass:: pqfilt.AndExpr

.. autoclass:: pqfilt.OrExpr

Operators
---------

.. automodule:: pqfilt._operators
   :members:
   :undoc-members:
