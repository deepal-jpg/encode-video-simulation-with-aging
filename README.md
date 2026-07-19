# Product Requirements Document (PRD)
**OS Sim: Preemptive Video Encoder**

---

## 1. Product Overview
* **Product Name:** OS Sim: Preemptive Video Encoder
* **Description:** A web-based simulation that visualizes how the *Shortest Job First (SJF) Preemptive* CPU scheduling algorithm behaves with an *Aging* mechanism.
* **Primary Goal:** Translate abstract Operating Systems concepts such as *Context Switch*, *Starvation*, and the *Process Control Block* queue into a real-world *video encoding* scenario that is easier for lecturers to evaluate and for students to understand.

## 2. Target Users
1. **Lecturer / Evaluator**
   * **Needs:** Logical accuracy of the algorithm, transparent process flow, and solid demonstration of OS concepts.
   * **Success Criteria:** The terminal log reports *Context Switch* and *Aging* events accurately without queue-related bugs.
2. **Fellow Students**
   * **Needs:** A visually engaging interface and a system simulation that is easy to understand.
   * **Success Criteria:** A clean educational interface with *real-time* updates and no need for manual page refreshes.

## 3. Functional Requirements
The application must provide the following core capabilities:
* **Job Input Module:** Users can submit a video name and *Burst Time* (estimated *render* time). The system automatically records *Arrival Time* using the system clock.
* **Scheduler Engine:**
  * **Preemption:** The system evaluates the queue every second. If a new video arrives with a smaller remaining time than the current one, the current process is paused through a *Context Switch*.
  * **Aging Mechanism:** The system increases priority by lowering the virtual remaining time of videos that have been waiting too long, preventing *Starvation*.
  * **Formula:** `Priority = Remaining_Time - (Waiting_Time * Aging_Factor)`
* **Live Dashboard:**
  * Displays the *Global Clock* (simulation time).
  * Shows a *Ready Queue* table that updates every second.
* **Terminal Log Event:** Prints the execution trace of the system, including when a process arrives, is *preempted*, *resumed*, and completed.

## 4. Non-Functional Requirements
* **Asynchronous Architecture:** The OS *clock tick* logic must run in a *background thread* so the web server does not freeze.
* **Real-Time Client Updates:** The interface fetches the system *state* every second through JSON polling using the JavaScript *Fetch API*.
* **Tech Stack:**
  * **Backend:** Python 3.x, Flask.
  * **Frontend:** HTML5, CSS3, Vanilla JavaScript ES6.

## 5. Demonstration User Flow
1. **Initialization:** The Flask server starts the OS clock thread at 00:00.
2. **Submit a Long Job:** The user submits `Video_A` with a burst time of 30s. `Video_A` starts running.
3. **Trigger Preemption:** At second 5, the user submits `Video_B` with a burst time of 10s. The terminal prints a *Context Switch*. `Video_B` takes over the CPU while `Video_A` returns to the waiting queue.
4. **Trigger Starvation and Aging:** The user continues submitting shorter videos. `Video_A` waits longer, and its virtual priority improves through *Aging*.
5. **Resolution:** *Aging* forces `Video_A` to run again even when shorter original jobs are present, preventing permanent *Starvation*.

## 6. Core Data Structure (Process Control Block)
Attributes stored in RAM for each *Job*:
* `PID`: Unique identifier (for example: `VID-1`)
* `Arrival Time`: Submission time
* `Burst Time`: Original execution time
* `Remaining Time`: Actual remaining execution time
* `Waiting Time`: Total time spent in the *Ready Queue*
* `Turnaround Time`: `Completion_Time - Arrival_Time`
* `Aging Factor`: Virtual reduction value based on waiting duration
