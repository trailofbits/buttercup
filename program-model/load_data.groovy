// We need to configure the console to have state:
// https://tinkerpop.apache.org/docs/current/reference/#console-sessions
:remote connect tinkerpop.server conf/remote.yaml session
:remote console

// 1 hour in milliseconds
:remote config timeout 3600000

println("Starting graph creation...")

g.io('data/graph.xml').read().iterate()

println("Graph creation complete.")

:remote console
:exit