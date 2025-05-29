# Exhibition Round 2

9 Delta Challenges (6 C, 3 Java), 6 Full Scan Challenges (4 C, 2 Java).

## Repositories

The following repositories were used during the Round:

- Libxml2 (C)
- Libpng (C)
- AIxCC Integration Test (C)
- FreeRDP (C)
- Sqlite (C)
- Dropbear (C)
- Zookeeper (Java)
- Apache Commons Compress (Java)

## Challenge Tasks Archive

Download all challenge tasks that were sent during the Round: [exhibition2_challenge_tasks.tar.gz](./exhibition2_challenge_tasks.tar.gz).

Note: Times included in tasks.json are descriptive of when the Competition API generated the task,
and not the exact times of when the message was broadcast to each CRS (it should be close though!).

## Sequencing

```mermaid
flowchart TD
  subgraph A["Challenge Set #0 (24 hr)"]
    direction LR
    A0["freerdp: Full 1"]
    B0["libxml2: Full 1"]
    C0["sqlite: Full 1"]
  end

  subgraph B["Challenge Set #1 (24 hr)"]
    direction LR
    A1["commons-compress: Full 1"]
    B1["zookeeper: Full 1"]
    C1["dropbear: Full 1"]
  end

  subgraph C["Challenge Set #2 (8 hr)"]
    direction LR
    A2["freerdp: Delta 1"]
    B2["libxml2: Delta 2"]
    C2["integration-test: Delta 1"]
    D2["libpng: Delta 1"]
  end

  subgraph D["Challenge Set #3 (8 hr)"]
    direction LR
    A3["sqlite: Delta 1"]
    B3["libxml2: Delta 1"]
  end

  subgraph E["Challenge Set #4 (8 hr)"]
    direction LR
    A4["zookeeper: Delta 1"]
    B4["commons-compress: Delta 2"]
    C4["commons-compress: Delta 3"]
  end

  subgraph F["\* Rerun Chal Set #1 (12 hr)"]
    direction LR
    A5["commons-compress: Full 1"]
    B5["zookeeper: Full 1"]
    C5["dropbear: Full 1"]
  end

  A --> B --> C --> D --> E --> F
```

## Notes

\* Challenge Set #1 was re-run during Exhibition Round 2 due to an upstream outage at OpenAI from 7:07pm ET on May 6th, 2025 to 3:15pm ET on May 8th, 2025.
As a result, CRS's using OpenAI were unable to make LLM API calls. The Organizers decided to re-run Challenge Set #1 as part of Exhibition 2 for 12 hours.
Challenge Set #0 had run successfully for ~5 hours before the outage. When access was restored, we reset budget amounts for all teams for Azure and LLMs and added a re-run of Challenge Set #1.
