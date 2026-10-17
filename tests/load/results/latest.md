# Load test 20261017T172540Z (commit fa08f92, 4.3 min)

Window 60 s per robot count, warm-up 15 s, VDA 2.

| check                                        |     limit |    10 robots |    25 robots |    50 robots |
|----------------------------------------------|-----------|--------------|--------------|--------------|
| state cadence p99 (periodic)                 | <=    1.2 |     1.009 ok |     1.018 ok |     1.038 ok |
| longest silence of a robot                   | <=    1.5 |     1.048 ok |     1.024 ok |     1.064 ok |
| headerId gaps                                | <=      0 |         0 ok |         0 ok |         0 ok |
| robot -> WebSocket latency p99               | <=    250 |        37 ok |      67.6 ok |     129.6 ok |
| WebSocket state events / MQTT state msgs     | >=   0.98 |         1 ok |         1 ok |         1 ok |
| events dropped by backend (slow client)      | <=      0 |         0 ok |         0 ok |         0 ok |
| time to first snapshot p99                   | <=   1000 |      47.4 ok |      37.9 ok |      62.2 ok |
| GET /api/robots p99                          | <=    200 |       9.9 ok |      19.3 ok |      15.9 ok |
| GET /api/messages p99                        | <=    200 |      19.6 ok |      32.5 ok |      22.1 ok |
| backend CPU mean (% of 1 core)               | <=     50 |       6.1 ok |       8.2 ok |      12.8 ok |
| backend CPU max (% of 1 core)                | <=     80 |       7.1 ok |      19.7 ok |      19.3 ok |
| simulator CPU mean (% of 1 core)             | <=     70 |       1.4 ok |         3 ok |       5.1 ok |
| mosquitto CPU mean (% of 1 core)             | <=     20 |       0.9 ok |       1.2 ok |       1.4 ok |
| backend memory max (MiB)                     | <=    300 |      48.2 ok |      49.3 ok |      49.8 ok |
| UI frames/s, median of 1 s buckets           | >=     30 |        60 ok |        60 ok |        60 ok |
| UI frame time p95                            | <=     50 |      16.7 ok |      16.7 ok |      16.8 ok |
| browser console errors                       | <=      0 |         0 ok |         0 ok |         0 ok |
| workload: busy robots (validity)             | >=   0.35 |      0.49 ok |      0.47 ok |      0.49 ok |
| MQTT msgs/s (uagv/#)                         |           |         10.8 |         26.7 |         53.8 |
| WebSocket events/s                           |           |         11.2 |         28.3 |         60.5 |
| WebSocket kB/s                               |           |         14.5 |         36.3 |         80.1 |
| snapshot kB                                  |           |        236.7 |        248.1 |        282.7 |
| robot -> WS latency p50 ms                   |           |         17.6 |         30.4 |         43.4 |
| robot -> WS p50 ms, burst / alone            |           |   18.2 / 6.3 |   30.8 / 6.1 |   44.2 / 6.5 |
| robot -> MQTT latency p99 ms                 |           |            7 |          8.8 |          8.7 |
| proximity events/s (WebSocket)               |           |          0.5 |          1.6 |          6.7 |
| UI main thread busy %                        |           |         40.5 |         46.1 |         49.5 |
| UI long tasks (count)                        |           |            0 |            0 |            0 |
| UI JS heap MiB                               |           |          9.5 |          9.5 |          9.5 |
| missions sent                                |           |           13 |           30 |           66 |
| host CPU % (all cores)                       |           |           23 |         23.6 |         25.4 |
