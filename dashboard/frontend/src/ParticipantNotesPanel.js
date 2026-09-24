// ParticipantNotesPanel.js - Study-personnel notes for a participant,
// plus the REDCap reminder switchboard that drives automated participant contact.
//
// Notes are never deleted: editing keeps the prior text as a revision, and
// retiring a note archives it.

import React, { useState, useEffect, useCallback } from 'react';
import {
  StickyNote, Plus, Pencil, Save, X, Pin, PinOff, Archive, ArchiveRestore,
  RefreshCw, History, Bell, BellOff, MinusCircle, AlertCircle,
} from 'lucide-react';
import { API_BASE_URL, authFetch } from './SocialScope';

const CATEGORY_STYLES = {
  general: { label: 'General', className: 'bg-gray-100 text-gray-700' },
  contact: { label: 'Contact', className: 'bg-blue-100 text-blue-700' },
  clinical: { label: 'Clinical', className: 'bg-red-100 text-red-700' },
  technical: { label: 'Technical', className: 'bg-purple-100 text-purple-700' },
  scheduling: { label: 'Scheduling', className: 'bg-amber-100 text-amber-800' },
};

const fmtDateTime = (value) => {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric',
    year: 'numeric', hour: 'numeric', minute: '2-digit',
  });
};

const CategoryBadge = ({ category }) => {
  const style = CATEGORY_STYLES[category] || CATEGORY_STYLES.general;
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${style.className}`}>
      {style.label}
    </span>
  );
};

const ParticipantNotesPanel = ({ participantId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const [draft, setDraft] = useState('');
  const [draftCategory, setDraftCategory] = useState('general');
  const [composing, setComposing] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState('');
  const [editCategory, setEditCategory] = useState('general');
  const [expandedRevisions, setExpandedRevisions] = useState({});

  const fetchNotes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(
        `${API_BASE_URL}/api/participant/${participantId}/notes?include_archived=${showArchived}`
      );
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to load notes');
      setData(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [participantId, showArchived]);

  useEffect(() => { fetchNotes(); }, [fetchNotes]);

  // Replace one note in place so the list doesn't jump while staff are working.
  const applyNote = (note) => setData((prev) => {
    if (!prev) return prev;
    const exists = prev.notes.some((n) => n.id === note.id);
    const notes = exists
      ? prev.notes.map((n) => (n.id === note.id ? note : n))
      : [note, ...prev.notes];
    return { ...prev, notes: showArchived ? notes : notes.filter((n) => !n.archived) };
  });

  const addNote = async () => {
    const text = draft.trim();
    if (!text) return;
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch(`${API_BASE_URL}/api/participant/${participantId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, category: draftCategory }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to save note');
      const { note } = await res.json();
      applyNote(note);
      setDraft('');
      setDraftCategory('general');
      setComposing(false);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  const updateNote = async (noteId, changes) => {
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch(
        `${API_BASE_URL}/api/participant/${participantId}/notes/${noteId}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(changes),
        }
      );
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to update note');
      const { note } = await res.json();
      applyNote(note);
      return true;
    } catch (e) { setError(e.message); return false; }
    finally { setSaving(false); }
  };

  const startEdit = (note) => {
    setEditingId(note.id);
    setEditText(note.text);
    setEditCategory(note.category || 'general');
  };

  const saveEdit = async () => {
    const text = editText.trim();
    if (!text) { setError('Note text cannot be empty'); return; }
    if (await updateNote(editingId, { text, category: editCategory })) setEditingId(null);
  };

  const notes = data?.notes || [];
  const categories = data?.categories || Object.keys(CATEGORY_STYLES);
  const reminders = data?.reminders;

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="px-6 py-4 border-b bg-gradient-to-r from-slate-50 to-blue-50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <StickyNote size={22} className="text-blue-600" />
          <div>
            <h2 className="text-lg font-semibold text-gray-800">Notes</h2>
            <p className="text-xs text-gray-500">
              Study-personnel notes and REDCap contact reminders for {participantId}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
            <input type="checkbox" checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)} />
            Show archived
          </label>
          <button onClick={fetchNotes} disabled={loading}
            className="p-1.5 rounded hover:bg-white text-gray-500 disabled:opacity-40"
            title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="p-6 space-y-6">
        {error && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* ---- Add a note ---- */}
        {composing ? (
          <div className="border border-blue-200 rounded-lg p-4 bg-blue-50/40 space-y-3">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
              autoFocus
              placeholder="What happened? Who did you contact, and what came of it?"
              className="w-full border border-gray-300 rounded p-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <div className="flex items-center justify-between flex-wrap gap-2">
              <select value={draftCategory} onChange={(e) => setDraftCategory(e.target.value)}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                {categories.map((c) => (
                  <option key={c} value={c}>{(CATEGORY_STYLES[c] || {}).label || c}</option>
                ))}
              </select>
              <div className="flex items-center gap-2">
                <button onClick={() => { setComposing(false); setDraft(''); setError(null); }}
                  className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 flex items-center gap-1">
                  <X size={14} /> Cancel
                </button>
                <button onClick={addNote} disabled={saving || !draft.trim()}
                  className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-40 flex items-center gap-1">
                  <Save size={14} /> {saving ? 'Saving…' : 'Save note'}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <button onClick={() => setComposing(true)}
            className="w-full border-2 border-dashed border-gray-300 rounded-lg py-3 text-sm text-gray-600 hover:border-blue-400 hover:text-blue-600 flex items-center justify-center gap-2">
            <Plus size={16} /> Add a note
          </button>
        )}

        {/* ---- Notes list ---- */}
        {loading && !data ? (
          <div className="flex justify-center py-6">
            <div className="animate-spin rounded-full h-7 w-7 border-4 border-blue-500 border-t-transparent" />
          </div>
        ) : notes.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-4">
            No notes yet for this participant.
          </p>
        ) : (
          <div className="space-y-3">
            {notes.map((note) => {
              const editing = editingId === note.id;
              return (
                <div key={note.id}
                  className={`border rounded-lg p-4 ${note.archived ? 'bg-gray-50 border-gray-200 opacity-75'
                    : note.pinned ? 'bg-amber-50/50 border-amber-300' : 'bg-white border-gray-200'}`}>
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2 flex-wrap text-xs text-gray-500">
                      <CategoryBadge category={note.category} />
                      {note.pinned && <Pin size={12} className="text-amber-600" />}
                      {note.archived && (
                        <span className="px-2 py-0.5 rounded-full bg-gray-200 text-gray-600">Archived</span>
                      )}
                      <span>{note.createdByName || note.createdBy || 'Unknown'}</span>
                      <span>·</span>
                      <span>{fmtDateTime(note.createdAt)}</span>
                      {note.revisionCount > 0 && (
                        <button
                          onClick={() => setExpandedRevisions((p) => ({ ...p, [note.id]: !p[note.id] }))}
                          className="flex items-center gap-1 text-blue-600 hover:underline">
                          <History size={12} />
                          edited {note.revisionCount}×
                        </button>
                      )}
                    </div>
                    {!editing && (
                      <div className="flex items-center gap-1 shrink-0">
                        <button onClick={() => updateNote(note.id, { pinned: !note.pinned })}
                          disabled={saving}
                          className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-40"
                          title={note.pinned ? 'Unpin' : 'Pin to top'}>
                          {note.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                        </button>
                        <button onClick={() => startEdit(note)}
                          className="p-1.5 rounded hover:bg-gray-100 text-gray-500" title="Edit">
                          <Pencil size={14} />
                        </button>
                        <button onClick={() => updateNote(note.id, { archived: !note.archived })}
                          disabled={saving}
                          className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-40"
                          title={note.archived ? 'Restore' : 'Archive (kept, just hidden)'}>
                          {note.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
                        </button>
                      </div>
                    )}
                  </div>

                  {editing ? (
                    <div className="space-y-2">
                      <textarea value={editText} onChange={(e) => setEditText(e.target.value)}
                        rows={4} autoFocus
                        className="w-full border border-gray-300 rounded p-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <select value={editCategory} onChange={(e) => setEditCategory(e.target.value)}
                          className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                          {categories.map((c) => (
                            <option key={c} value={c}>{(CATEGORY_STYLES[c] || {}).label || c}</option>
                          ))}
                        </select>
                        <div className="flex items-center gap-2">
                          <button onClick={() => { setEditingId(null); setError(null); }}
                            className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 flex items-center gap-1">
                            <X size={14} /> Cancel
                          </button>
                          <button onClick={saveEdit} disabled={saving || !editText.trim()}
                            className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-40 flex items-center gap-1">
                            <Save size={14} /> {saving ? 'Saving…' : 'Save'}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{note.text}</p>
                  )}

                  {expandedRevisions[note.id] && note.revisions?.length > 0 && (
                    <div className="mt-3 border-t pt-3 space-y-2">
                      <div className="text-xs font-semibold text-gray-500">Earlier versions</div>
                      {note.revisions.slice().reverse().map((rev, idx) => (
                        <div key={idx} className="text-xs bg-gray-50 border border-gray-200 rounded p-2">
                          <div className="text-gray-500 mb-1">
                            {fmtDateTime(rev.editedAt)} · {rev.editedBy || 'unknown'}
                          </div>
                          <div className="text-gray-700 whitespace-pre-wrap break-words">{rev.text}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ---- REDCap reminders ---- */}
        <div className="border-t pt-5">
          <div className="flex items-center gap-2 mb-1">
            <Bell size={16} className="text-indigo-600" />
            <h3 className="text-sm font-semibold text-gray-800">REDCap Contact Reminders</h3>
            {reminders?.updatedAt && (
              <span className="text-xs text-gray-400">updated {fmtDateTime(reminders.updatedAt)}</span>
            )}
          </div>
          <p className="text-xs text-gray-500 mb-3">
            The automated-contact switches on the REDCap <code>reminders</code> form. Read-only
            here — change them in REDCap.
          </p>

          {!reminders ? null : reminders.available === false ? (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-3">
              Reminder status unavailable: {reminders.reason || 'REDCap did not respond'}
            </div>
          ) : (
            <>
              {!reminders.hasData && (
                <div className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded p-3 mb-3">
                  No reminders have been set for this participant yet.
                </div>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                {(reminders.reminders || []).map((r) => (
                  <div key={r.field}
                    className={`flex items-start gap-2 border rounded px-3 py-2 text-xs ${
                      r.send ? 'bg-green-50 border-green-200'
                        : r.cancelled ? 'bg-gray-50 border-gray-200'
                        : 'bg-white border-gray-100'}`}>
                    {r.send ? <Bell size={14} className="text-green-600 mt-0.5 shrink-0" />
                      : r.cancelled ? <BellOff size={14} className="text-gray-500 mt-0.5 shrink-0" />
                      : <MinusCircle size={14} className="text-gray-300 mt-0.5 shrink-0" />}
                    <div className="min-w-0">
                      <div className="text-gray-800 break-words">{r.label}</div>
                      <div className={r.send ? 'text-green-700 font-medium'
                        : r.cancelled ? 'text-gray-600' : 'text-gray-400'}>
                        {r.valueLabel}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default ParticipantNotesPanel;
