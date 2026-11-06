## Purpose

Runs the app's background work, such as sending reminders, on a schedule inside the one backend process, with when each job is next due kept in Postgres, so that work is neither lost nor run twice at once across restarts.

## ADDED Requirements

### Requirement: Jobs run on a schedule in the backend process

The backend SHALL run each registered job again after its interval, from one loop inside the backend process, started when the backend starts and needing no other service. The time each job is next due SHALL be kept in the database. A job SHALL NOT run twice at the same time. Jobs SHALL run whenever the backend runs, in every auth mode, and no operator setting SHALL turn them off. A row kept for a job that is no longer registered SHALL NOT make the runner wake more often than once a second.

#### Scenario: A job runs after its interval

- **WHEN** a job with an interval of 30 seconds last ran at 12:00:00
- **THEN** it runs again at about 12:00:30, and not before

#### Scenario: Demo mode

- **WHEN** the backend starts in demo mode and a demo visitor's reminder comes due
- **THEN** the reminder job runs and the visitor gets the in-app notification

#### Scenario: A job that was removed

- **WHEN** the database holds a row for a job that is no longer registered, last due an hour ago
- **THEN** the runner leaves that row as it is, and runs the registered jobs on their schedule without waking more than once a second

#### Scenario: One run at a time

- **WHEN** two loops try to run the same due job at the same moment
- **THEN** only one of them runs it

### Requirement: A job missed while the backend was down runs once

A job that became due while the backend was not running SHALL run once soon after the backend starts, and SHALL NOT run once for each interval it missed. A run that was cut off by a crash or a shutdown SHALL run again when the backend next starts, without waiting for its interval.

#### Scenario: Down for an hour

- **WHEN** a job with an interval of 30 seconds was not run for an hour because the backend was stopped, and the backend starts
- **THEN** the job runs once, and then again 30 seconds later

#### Scenario: Cut off by a crash

- **WHEN** the backend process is killed while a daily job is running, and the backend starts again an hour later
- **THEN** the job runs again at start, not a day later

### Requirement: A failing job does not stop the others

A job that raises an error or runs longer than its time limit SHALL be logged with its name, SHALL be tried again after its interval or after 5 minutes, whichever is sooner, and SHALL NOT stop other jobs from running. An error outside any job, such as the database being unreachable while the runner reads or claims a job, SHALL be logged, and the runner SHALL try again within a minute and SHALL NOT stop until the backend shuts down.

#### Scenario: One job fails

- **WHEN** one job raises an error on every run and another job is due
- **THEN** the other job still runs on its schedule
- **AND** the failing job is tried again no sooner than its interval or 5 minutes allows

#### Scenario: Database restarted

- **WHEN** the database cannot be reached for a while as the runner claims a job, and then can again
- **THEN** the runner logs the error, keeps running, and runs the due job once the database is back, without a backend restart

### Requirement: Jobs stop cleanly with the backend

When the backend shuts down, it SHALL stop starting jobs, SHALL let a running job finish for up to 5 seconds, and SHALL then cancel it. It SHALL do this at the same time as it stops running answers, so a running job does not make the shutdown longer than stopping the answers alone. A cancelled job's unfinished writes SHALL NOT be kept, and the job SHALL run again when the backend next starts.

#### Scenario: Shutdown during a run

- **WHEN** the backend receives a shutdown while a job is part way through its writes, and the job does not finish within 5 seconds
- **THEN** the job is cancelled and none of its unfinished writes are kept
- **AND** the job runs at the next start

#### Scenario: Shutdown with a job and an answer running

- **WHEN** the backend receives a shutdown while a slow job and an answer are both running
- **THEN** it finishes shutting down within about 6 seconds, and the answer is stored as interrupted
