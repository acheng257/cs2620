Machine
=======

.. module:: src.machine

The Machine module implements a node in a distributed system using a logical clock.

Machine Class
---------------------------------------

.. autoclass:: src.machine.Machine
   :members:
   :special-members: __init__
   :undoc-members:
   :show-inheritance:

Event Types
-------------------------------------

The machine handles three types of events:

* ``INTERNAL``: Internal events that only affect the local machine
* ``SEND``: Events where the machine sends a message to another machine
* ``RECEIVE``: Events where the machine receives a message from another machine

Message Format
----------------------------------------

Messages are formatted as strings with fields separated by '|':

.. code-block:: text

   sender_id|sender_timestamp|message_content

Logging Format
----------------------------------------

Each log entry follows this format:

.. code-block:: text

   [SystemTime=<time>] [Machine=<id>] [LogicalClock=<clock>] [Event=<type>] <detail>

Example Usage
---------------------------------------

.. code-block:: python

   from src.machine import Machine

   # Create a machine instance
   machine = Machine(
       id=1,
       host="localhost",
       port=8765,
       neighbors=[("localhost", 8766), ("localhost", 8767)]
   )

   # Start the machine
   machine.run() 