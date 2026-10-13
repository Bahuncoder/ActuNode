# Load test 20261013T164702Z (commit 79a3c3e, 5.2 min)

Window 60 s per robot count, warm-up 15 s, VDA 2.

| check                                        |     limit |    10 robots |    25 robots |    50 robots |
|----------------------------------------------|-----------|--------------|--------------|--------------|
| state cadence p99 (periodic)                 | <=    1.2 |     1.007 ok |     1.019 ok |     1.032 ok |
| longest silence of a robot                   | <=    1.5 |     1.047 ok |     1.029 ok |     1.068 ok |
| headerId gaps                                | <=      0 |         0 ok |         0 ok |         0 ok |
| robot -> WebSocket latency p99               | <=    250 |      36.9 ok |      60.2 ok |      76.3 ok |
| WebSocket state events / MQTT state msgs     | >=   0.98 |    0.9984 ok |         1 ok |    0.9997 ok |
| events dropped by backend (slow client)      | <=      0 |         0 ok |         0 ok |         0 ok |
| time to first snapshot p99                   | <=   1000 |      41.4 ok |      41.4 ok |      50.2 ok |
| GET /api/robots p99                          | <=    200 |      33.8 ok |      12.6 ok |      56.6 ok |
| GET /api/messages p99                        | <=    200 |      35.1 ok |      14.6 ok |      43.7 ok |
| backend CPU mean (% of 1 core)               | <=     50 |       5.7 ok |       7.6 ok |      10.5 ok |
| backend CPU max (% of 1 core)                | <=     80 |       4.7 ok |      19.6 ok |      22.3 ok |
| simulator CPU mean (% of 1 core)             | <=     70 |       1.5 ok |       2.8 ok |       4.9 ok |
| mosquitto CPU mean (% of 1 core)             | <=     20 |         1 ok |       1.1 ok |       1.3 ok |
| backend memory max (MiB)                     | <=    300 |      46.6 ok |      47.4 ok |      47.4 ok |
| UI frames/s, median of 1 s buckets           | >=     30 |        60 ok |        60 ok |        60 ok |
| UI frame time p95                            | <=     50 |      16.7 ok |      16.8 ok |     16.75 ok |
| browser console errors                       | <=      0 |         0 ok |         0 ok |         0 ok |
| workload: busy robots (validity)             | >=   0.35 |      0.49 ok |      0.47 ok |      0.49 ok |
| MQTT msgs/s (uagv/#)                         |           |         10.7 |         26.7 |         53.7 |
| WebSocket events/s                           |           |         11.2 |         28.6 |         59.7 |
| WebSocket kB/s                               |           |         14.5 |         36.2 |         78.5 |
| snapshot kB                                  |           |        236.6 |        244.5 |        287.3 |
| robot -> WS latency p50 ms                   |           |         17.2 |         22.7 |         39.1 |
| robot -> WS p50 ms, burst / alone            |           |   18.6 / 5.8 |   23.4 / 5.2 |   39.6 / 5.0 |
| robot -> MQTT latency p99 ms                 |           |          7.9 |           25 |         10.6 |
| proximity events/s (WebSocket)               |           |          0.5 |          1.9 |            6 |
| UI main thread busy %                        |           |         41.1 |         42.9 |         48.1 |
| UI long tasks (count)                        |           |            0 |            0 |            0 |
| UI JS heap MiB                               |           |          9.5 |          9.5 |         10.7 |
| missions sent                                |           |           13 |           30 |           65 |
| host CPU % (all cores)                       |           |          7.6 |          8.1 |          9.1 |
