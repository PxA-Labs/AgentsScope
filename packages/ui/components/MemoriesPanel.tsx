import React from "react";
import { AlertTriangle, Brain, Search, Tag, Trash2 } from "lucide-react";
import type { MemoriesState } from "../hooks/useMemories";
import type { MemoryItem } from "../types";

function MemoryCard({ memory: m, onDelete }: { memory: MemoryItem; onDelete: (id: string) => void }) {
  const dateStr = m.created_at ? new Date(m.created_at).toLocaleString() : "";
  const agentName = (m.metadata?.agent_name || m.metadata?.agent) as React.ReactNode;
  // Prefer top-level categories, falling back to metadata. A single resolved
  // list keeps the render guard and the map in sync.
  const cats: string[] = m.categories?.length
    ? m.categories
    : ((m.metadata?.categories as string[] | undefined) ?? []);
  return (
    <div className="p-4 rounded-xl border border-border bg-secondary/10 hover:bg-secondary/20 transition-all duration-200 flex flex-col justify-between gap-3 group relative">
      <div className="pr-8">
        <p className="text-xs font-medium text-white leading-relaxed whitespace-pre-wrap">
          {m.memory}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground font-mono mt-2 pt-2 border-t border-border/30">
        {dateStr && <span className="bg-secondary px-2 py-0.5 rounded-md">{dateStr}</span>}
        {agentName && (
          <span className="bg-purple-900/30 text-purple-300 border border-purple-500/20 px-2 py-0.5 rounded-md">
            Agent: {agentName}
          </span>
        )}
        {cats.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            {cats.map((cat, idx) => (
              <span
                key={idx}
                className="bg-blue-900/30 text-blue-300 border border-blue-500/20 px-2 py-0.5 rounded-md flex items-center gap-1"
              >
                <Tag className="w-2.5 h-2.5" />
                {cat}
              </span>
            ))}
          </div>
        )}
      </div>
      <button
        onClick={() => onDelete(m.id)}
        className="absolute top-4 right-4 p-1.5 rounded-lg bg-transparent hover:bg-rose-500/10 text-muted-foreground hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-all duration-200"
        title="Delete memory"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}

/** "Mem0 Memories" tab: semantic search, manual add and the memory cards. */
export function MemoriesPanel({
  memories,
  memoryQuery,
  setMemoryQuery,
  isSearchingMemories,
  newMemoryText,
  setNewMemoryText,
  newMemoryCategories,
  setNewMemoryCategories,
  isAddingMemory,
  mem0Error,
  handleSearchMemories,
  handleResetSearch,
  handleAddMemory,
  handleDeleteMemory,
}: MemoriesState) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden p-4 pt-0 gap-4">
      {/* Search & Add Controls */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-shrink-0">
        {/* Search Memories */}
        <form
          onSubmit={handleSearchMemories}
          className="glass-panel p-4 rounded-2xl border border-border flex items-center gap-3 bg-card/40"
        >
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
            <input
              type="text"
              placeholder="Semantic search memories..."
              value={memoryQuery}
              onChange={(e) => setMemoryQuery(e.target.value)}
              className="w-full bg-secondary/40 text-xs pl-9 pr-3 py-2 rounded-xl border border-border focus:outline-none focus:border-purple-500/50 text-white"
            />
          </div>
          <button
            type="submit"
            disabled={isSearchingMemories}
            className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 font-bold text-xs text-white transition-all duration-200 disabled:opacity-50"
          >
            {isSearchingMemories ? "Searching..." : "Search"}
          </button>
          {memoryQuery && (
            <button
              type="button"
              onClick={handleResetSearch}
              className="text-xs text-muted-foreground hover:text-white underline"
            >
              Reset
            </button>
          )}
        </form>

        {/* Add Memory */}
        <form
          onSubmit={handleAddMemory}
          className="glass-panel p-4 rounded-2xl border border-border flex flex-col sm:flex-row items-center gap-3 bg-card/40"
        >
          <input
            type="text"
            placeholder="Add a new custom memory..."
            value={newMemoryText}
            onChange={(e) => setNewMemoryText(e.target.value)}
            className="flex-1 w-full bg-secondary/40 text-xs px-3 py-2 rounded-xl border border-border focus:outline-none focus:border-purple-500/50 text-white"
          />
          <input
            type="text"
            placeholder="Categories (e.g. preferences, facts)..."
            value={newMemoryCategories}
            onChange={(e) => setNewMemoryCategories(e.target.value)}
            className="w-full sm:w-60 bg-secondary/40 text-xs px-3 py-2 rounded-xl border border-border focus:outline-none focus:border-purple-500/50 text-white"
          />
          <button
            type="submit"
            disabled={isAddingMemory || !newMemoryText.trim()}
            className="w-full sm:w-auto px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 font-bold text-xs text-white transition-all duration-200 disabled:opacity-50 whitespace-nowrap"
          >
            {isAddingMemory ? "Adding..." : "Add Memory"}
          </button>
        </form>
      </div>

      {/* Memories Display Panel */}
      <section className="flex-1 flex flex-col overflow-hidden glass-panel rounded-2xl border border-border">
        <div className="p-4 border-b border-border bg-card/40 flex items-center justify-between">
          <h3 className="font-bold text-xs uppercase tracking-wider text-white flex items-center gap-2">
            <Brain className="w-4 h-4 text-purple-400" /> Extracted Session Memories
          </h3>
          <span className="text-[10px] text-muted-foreground font-mono">
            {memories.length} Memories Stored
          </span>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {mem0Error && (
            <div className="mb-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 flex-shrink-0" />
              <div>
                <p className="font-bold mb-1">Configuration Warning</p>
                <p>{mem0Error}</p>
              </div>
            </div>
          )}

          {memories.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {memories.map((m) => (
                <MemoryCard key={m.id} memory={m} onDelete={handleDeleteMemory} />
              ))}
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
              <Brain className="w-12 h-12 text-muted-foreground/30 mb-2 animate-pulse" />
              <p className="text-xs font-bold text-white mb-1">No Memories Found</p>
              <p className="text-[10px] max-w-sm leading-relaxed opacity-60">
                Memories are automatically extracted from agent LLM conversations in real-time when{" "}
                <code>llm_end</code> events are logged.
              </p>
              <p className="text-[10px] max-w-sm mt-1 leading-relaxed opacity-60">
                You can also inject memories manually using the inputs above.
              </p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
