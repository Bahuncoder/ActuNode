# Load test 20261012T192608Z (commit 45e548e, 4.3 min)

Window 60 s per robot count, warm-up 15 s, VDA 2.

| check                                        |     limit |    10 robots |    25 robots |    50 robots |
|----------------------------------------------|-----------|--------------|--------------|--------------|
| state cadence p99 (periodic)                 | <=    1.2 |     1.009 ok |     1.017 ok |      1.03 ok |
| longest silence of a robot                   | <=    1.5 |     1.011 ok |     1.056 ok |     1.051 ok |
| headerId gaps                                | <=      0 |         0 ok |         0 ok |         0 ok |
| robot -> WebSocket latency p99               | <=    250 |      33.9 ok |      67.5 ok |      75.1 ok |
| WebSocket state events / MQTT state msgs     | >=   0.98 |         1 ok |         1 ok |         1 ok |
| events dropped by backend (slow client)      | <=      0 |         0 ok |         0 ok |         0 ok |
| time to first snapshot p99                   | <=   1000 |      39.2 ok |        45 ok |      43.8 ok |
| GET /api/robots p99                          | <=    200 |      15.9 ok |      19.9 ok |      26.2 ok |
| GET /api/messages p99                        | <=    200 |      15.9 ok |      17.7 ok |      17.6 ok |
| backend CPU mean (% of 1 core)               | <=     50 |       5.6 ok |       7.4 ok |      10.3 ok |
| backend CPU max (% of 1 core)                | <=     80 |       4.6 ok |      17.9 ok |      21.1 ok |
| simulator CPU mean (% of 1 core)             | <=     70 |       1.2 ok |       2.4 ok |       4.4 ok |
| mosquitto CPU mean (% of 1 core)             | <=     20 |         1 ok |       1.1 ok |       1.5 ok |
| backend memory max (MiB)                     | <=    300 |      46.1 ok |      52.1 ok |      47.2 ok |
| UI frames/s, median of 1 s buckets           | >=     30 |        60 ok |        60 ok |        59 ok |
| UI frame time p95                            | <=     50 |      16.7 ok |      16.7 ok |      16.8 ok |
| browser console errors                       | <=      0 |         0 ok |         0 ok |         0 ok |
| workload: busy robots (validity)             | >=   0.35 |      0.49 ok |      0.47 ok |      0.49 ok |
| MQTT msgs/s (uagv/#)                         |           |         10.7 |         26.6 |         53.7 |
| WebSocket events/s                           |           |         11.2 |         28.6 |         59.6 |
| WebSocket kB/s                               |           |           14 |         35.3 |         76.2 |
| snapshot kB                                  |           |        230.1 |          246 |        283.3 |
| robot -> WS latency p50 ms                   |           |         15.9 |         21.7 |         39.6 |
| robot -> WS p50 ms, burst / alone            |           |   16.7 / 5.3 |   22.0 / 3.2 |   40.3 / 4.0 |
| robot -> MQTT latency p99 ms                 |           |          5.9 |         11.6 |          8.4 |
| proximity events/s (WebSocket)               |           |          0.5 |            2 |          5.9 |
| UI main thread busy %                        |           |         37.4 |         35.5 |         48.2 |
| UI long tasks (count)                        |           |            0 |            0 |            0 |
| UI JS heap MiB                               |           |          9.5 |          9.5 |          9.5 |
| missions sent                                |           |           13 |           29 |           65 |
| host CPU % (all cores)                       |           |         10.2 |         15.2 |         12.6 |
