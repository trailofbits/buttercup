// We need to configure the console to have state:
// https://tinkerpop.apache.org/docs/current/reference/#console-sessions
:remote connect tinkerpop.server conf/remote.yaml session
:remote console

// 1 hour in milliseconds
:remote config timeout 3600000

println("Printing schema...")

mgmt = graph.openManagement()
mgmt.printSchema()

println("Starting graph creation...")

g.io('/crs_scratch/graph.xml').read().iterate()

println("Graph creation complete.")

:remote console
:exit
