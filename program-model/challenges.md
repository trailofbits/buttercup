# Challenges

Details of challenges tested.

## [libpng](https://github.com/aixcc-finals/example-libpng)

* 2 minutes to write graphml file
  * Takes about 8 GB of memory
* Outputted:
  * Nodes:   424,350
  * Edges: 3,706,932

* 14 minutes to load into JanusGraph
  * Takes about 10 GB of memory
* Outputted:
  * Nodes:   217,060
  * Edges: 1,853,466

**TODO:** Reconcile the differences in the number of nodes and edges.

### Full-scan

* **base:** `2c894c66108f0724331a9e5b4826e351bf2d094b`

### Delta-scan

* **base:** `0cc367aaeaac3f888f255cee5d394968996f736e`
* **delta:** `2c894c66108f0724331a9e5b4826e351bf2d094b`
