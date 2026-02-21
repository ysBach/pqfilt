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
   :members:
   :undoc-members:

.. autoclass:: pqfilt.AndExpr
   :members:
   :undoc-members:

.. autoclass:: pqfilt.OrExpr
   :members:
   :undoc-members:

Operators
---------

.. automodule:: pqfilt._operators
   :members:
   :undoc-members:
