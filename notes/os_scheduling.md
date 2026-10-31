# CPU Scheduling

CPU scheduling decides which process in the ready queue gets the CPU next. Key metrics are waiting time (time spent in the ready queue), turnaround time (completion time minus arrival time) and response time.

First Come First Served (FCFS): processes run in arrival order. It is simple but suffers from the convoy effect, where short processes wait behind a long one.

Shortest Job First (SJF): picks the process with the smallest burst time. It gives the minimum average waiting time but needs to know burst times and can starve long processes. The preemptive version is called Shortest Remaining Time First (SRTF).

Round Robin (RR): each process gets a fixed time quantum and then goes to the back of the queue. It is fair and good for time-sharing systems. A very large quantum behaves like FCFS; a very small quantum wastes time on context switches.

Priority scheduling: the highest priority process runs first. Low priority processes may starve, which is solved by aging, gradually raising the priority of waiting processes.
