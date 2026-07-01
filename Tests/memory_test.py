from Memory.memory_engine import MemoryEngine

memory = MemoryEngine()

memory.save("gym", "6 PM")
memory.save("college", "Loyola Institute of Technology")

print(memory.recall("gym"))
print(memory.recall("college"))