# Load test 20261015T033420Z (commit bb7ec88, 4.4 min)

Window 60 s per robot count, warm-up 15 s, VDA 2.

| check                                        |     limit |    10 robots |    25 robots |    50 robots |
|----------------------------------------------|-----------|--------------|--------------|--------------|
| state cadence p99 (periodic)                 | <=    1.2 |     1.013 ok |     1.015 ok |     1.103 ok |
| longest silence of a robot                   | <=    1.5 |     1.017 ok |     1.046 ok |     1.133 ok |
| headerId gaps                                | <=      0 |         0 ok |         0 ok |         0 ok |
| robot -> WebSocket latency p99               | <=    250 |      58.8 ok |       117 ok |     213.7 ok |
| WebSocket state events / MQTT state msgs     | >=   0.98 |         1 ok |         1 ok |         1 ok |
| events dropped by backend (slow client)      | <=      0 |         0 ok |         0 ok |         0 ok |
| time to first snapshot p99                   | <=   1000 |      73.7 ok |      62.9 ok |      80.5 ok |
| GET /api/robots p99                          | <=    200 |      20.8 ok |      17.2 ok |      27.4 ok |
| GET /api/messages p99                        | <=    200 |      20.9 ok |      28.5 ok |      27.9 ok |
| backend CPU mean (% of 1 core)               | <=     50 |       8.5 ok |      16.3 ok |      23.7 ok |
| backend CPU max (% of 1 core)                | <=     80 |         7 ok |      25.5 ok |      30.3 ok |
| simulator CPU mean (% of 1 core)             | <=     70 |       1.4 ok |       4.3 ok |       7.5 ok |
| mosquitto CPU mean (% of 1 core)             | <=     20 |       1.9 ok |       2.3 ok |       2.8 ok |
| backend memory max (MiB)                     | <=    300 |      47.2 ok |        50 ok |      51.9 ok |
| UI frames/s, median of 1 s buckets           | >=     30 |      57.5 ok |      53.5 ok |        54 ok |
| UI frame time p95                            | <=     50 |      16.8 ok |      33.3 ok |      33.4 ok |
| browser console errors                       | <=      0 |         0 ok |         0 ok |         0 ok |
| workload: busy robots (validity)             | >=   0.35 |      0.49 ok |      0.47 ok |      0.49 ok |
| MQTT msgs/s (uagv/#)                         |           |         10.8 |         26.5 |         53.4 |
| WebSocket events/s                           |           |         11.3 |         28.3 |         59.5 |
| WebSocket kB/s                               |           |         14.5 |         36.6 |         77.6 |
| snapshot kB                                  |           |          237 |        252.6 |        280.6 |
| robot -> WS latency p50 ms                   |           |         22.1 |         73.7 |        109.4 |
| robot -> WS p50 ms, burst / alone            |           |   24.2 / 5.6 |   74.9 / 6.8 |  115.3 / 7.9 |
| robot -> MQTT latency p99 ms                 |           |         17.1 |         11.9 |         92.8 |
| proximity events/s (WebSocket)               |           |          0.5 |          1.9 |          6.1 |
| UI main thread busy %                        |           |         59.8 |         77.8 |           74 |
| UI long tasks (count)                        |           |            0 |            2 |            4 |
| UI JS heap MiB                               |           |          9.5 |          9.5 |         10.7 |
| missions sent                                |           |           13 |           30 |           64 |
| host CPU % (all cores)                       |           |         34.3 |         24.7 |           21 |
