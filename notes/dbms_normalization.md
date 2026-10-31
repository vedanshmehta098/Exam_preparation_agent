# Normalization

Normalization is the process of organising a relational database to reduce data redundancy and avoid insertion, update and deletion anomalies. It works by splitting big tables into smaller ones linked by keys.

First Normal Form (1NF): every column holds atomic (indivisible) values and there are no repeating groups. A cell like "Maths, Physics" violates 1NF.

Second Normal Form (2NF): the table is in 1NF and has no partial dependency, meaning no non-key attribute depends on only a part of a composite primary key. 2NF only matters when the primary key is composite.

Third Normal Form (3NF): the table is in 2NF and has no transitive dependency, meaning no non-key attribute depends on another non-key attribute. Example: StudentID -> PinCode -> City is transitive, so City should move to a separate table.

Boyce-Codd Normal Form (BCNF): a stricter version of 3NF. For every functional dependency X -> Y, X must be a super key. Every BCNF table is in 3NF, but not every 3NF table is in BCNF.

Functional dependency: X -> Y means that if two rows have the same X value they must have the same Y value. Armstrong's axioms (reflexivity, augmentation, transitivity) are used to derive new dependencies.

Denormalization deliberately adds redundancy back to make read-heavy queries faster, at the cost of extra storage and harder updates.
