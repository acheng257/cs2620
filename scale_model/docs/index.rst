Welcome to Scale Model's documentation!
========================================================

Scale Model is a distributed system implementation of scale models with logical clocks, message passing and event ordering.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   modules/machine
   modules/network

Overview
--------

This project implements a distributed system where multiple machines communicate via message passing,
maintaining logical clock synchronization using. Each machine runs at a different
clock rate and logs its events with both system time and logical clock values.

Features
--------

* Implementation of Logical Clocks
* Distributed message passing system
* Event logging with system time and logical clocks
* Configurable machine instances with different clock rates
* TCP-based network communication

Getting Started
------------------------------------------

For detailed setup instructions, usage examples, and development guidelines, please refer to the project's README.md file.

The README includes information about:

* Installation with Pipenv
* Running the distributed system
* Development tools and commands
* Testing and coverage
* Documentation building

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search` 