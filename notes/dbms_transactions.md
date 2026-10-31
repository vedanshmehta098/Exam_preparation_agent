# Transactions and Concurrency

A transaction is a logical unit of work made of one or more operations that must either all succeed or all fail. The ACID properties describe a reliable transaction.

Atomicity: all operations happen or none do. If a failure occurs midway, the system rolls back the partial changes.

Consistency: a transaction takes the database from one valid state to another valid state, respecting all constraints.

Isolation: concurrent transactions behave as if they ran one after another, so intermediate states are not visible to others.

Durability: once a transaction commits, its changes survive crashes, because they are written to the log on stable storage.

Concurrency problems: dirty read (reading uncommitted data of another transaction), non-repeatable read (the same row gives different values when read twice), and phantom read (a repeated query returns new rows).

Isolation levels from weakest to strongest: Read Uncommitted, Read Committed, Repeatable Read, Serializable. Serializable prevents all three problems but reduces concurrency.

Two-phase locking (2PL): a transaction first acquires locks (growing phase) and then only releases them (shrinking phase). 2PL guarantees conflict serializability but can cause deadlock. A deadlock is when two transactions wait for each other forever; it is handled by detection using a wait-for graph or by prevention with timeouts.
