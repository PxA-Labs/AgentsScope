"use client";

import React, { useCallback, useEffect, useState } from "react";
import { addMemory, deleteMemory, listMemories, searchMemories } from "../lib/api";
import type { MemoryItem, Session } from "../types";

/**
 * State and actions for the Mem0 memories tab. Lives in the page (not the
 * panel) so the list, inputs and errors survive switching tabs. Memories are
 * (re)loaded whenever the tab is shown or the active session changes while
 * it is shown.
 */
export function useMemories(activeSession: Session | null, visible: boolean) {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [isSearchingMemories, setIsSearchingMemories] = useState(false);
  const [newMemoryText, setNewMemoryText] = useState("");
  const [newMemoryCategories, setNewMemoryCategories] = useState("");
  const [isAddingMemory, setIsAddingMemory] = useState(false);
  const [mem0Error, setMem0Error] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    if (!activeSession) return;
    try {
      setMem0Error(null);
      const result = await listMemories(activeSession.session_id);
      if (result.ok) {
        setMemories(result.data.results || []);
      } else {
        setMem0Error(result.detail || "Failed to load memories");
      }
    } catch (e) {
      console.warn("Failed to fetch memories", e);
      setMem0Error("Could not connect to memories endpoint.");
    }
  }, [activeSession]);

  useEffect(() => {
    if (visible && activeSession) {
      // fetchMemories clears the previous error before its request (also on
      // manual reloads), so showing the tab hides a stale warning right away.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      fetchMemories();
    }
  }, [visible, activeSession, fetchMemories]);

  const handleSearchMemories = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!activeSession) return;
    if (!memoryQuery.trim()) {
      fetchMemories();
      return;
    }
    try {
      setIsSearchingMemories(true);
      setMem0Error(null);
      const result = await searchMemories(activeSession.session_id, memoryQuery);
      if (result.ok) {
        setMemories(result.data.results || []);
      } else {
        setMem0Error(result.detail || "Failed to search memories");
      }
    } catch (e) {
      console.warn("Failed to search memories", e);
      setMem0Error("Could not connect to memories search endpoint.");
    } finally {
      setIsSearchingMemories(false);
    }
  };

  const handleResetSearch = () => {
    setMemoryQuery("");
    fetchMemories();
  };

  const handleAddMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSession || !newMemoryText.trim()) return;
    try {
      setIsAddingMemory(true);
      setMem0Error(null);
      const parsedCategories = newMemoryCategories
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean);
      const payload: { text: string; categories?: string[] } = {
        text: newMemoryText,
      };
      if (parsedCategories.length > 0) {
        payload.categories = parsedCategories;
      }
      const result = await addMemory(activeSession.session_id, payload);
      if (result.ok) {
        setNewMemoryText("");
        setNewMemoryCategories("");
        setTimeout(fetchMemories, 1000);
      } else {
        setMem0Error(result.detail || "Failed to add memory");
      }
    } catch (e) {
      console.warn("Failed to add memory", e);
      setMem0Error("Could not connect to memories creation endpoint.");
    } finally {
      setIsAddingMemory(false);
    }
  };

  const handleDeleteMemory = async (memoryId: string) => {
    if (!activeSession) return;
    try {
      const result = await deleteMemory(activeSession.session_id, memoryId);
      if (result.ok) {
        setMemories((prev) => prev.filter((m) => m.id !== memoryId));
      } else {
        setMem0Error(result.detail || "Failed to delete memory");
      }
    } catch (e) {
      console.warn("Failed to delete memory", e);
      setMem0Error("Could not connect to memories deletion endpoint.");
    }
  };

  return {
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
  };
}

export type MemoriesState = ReturnType<typeof useMemories>;
