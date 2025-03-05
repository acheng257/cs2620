Network
=======

.. module:: src.network

The Network module provides TCP socket-based communication functionality for the distributed system.

Classes
-------

ServerWrapper
~~~~~~~~~~~~

.. autoclass:: src.network.ServerWrapper
   :members:
   :special-members: __init__
   :undoc-members:
   :show-inheritance:

Functions
---------

.. autofunction:: src.network.start_server

.. autofunction:: src.network.send_message

Example Usage
------------

Starting a Server
~~~~~~~~~~~~~~~~

.. code-block:: python

   from src.network import start_server

   def message_handler(message):
       print(f"Received message: {message}")

   # Start a server on localhost:8765
   server = start_server("localhost", 8765, message_handler)

Sending Messages
~~~~~~~~~~~~~~

.. code-block:: python

   from src.network import send_message

   # Send a message to a machine
   send_message("localhost", 8765, "Hello, Machine!") 