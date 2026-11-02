from ns import ns

nodes = ns.NodeContainer()
nodes.Create(3)
print(f"Created {nodes.GetN()} nodes")

ns.Simulator.Stop(ns.Seconds(1.0))
ns.Simulator.Run()
print(f"Simulated time: {ns.Simulator.Now().GetSeconds()} s")
ns.Simulator.Destroy()
print("ns-3 OK")
