import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import './IdentityViewer.css';

interface IdentityData {
  identity_document: string;
  version: number;
  last_updated: string;
}

interface IdentityViewerProps {
  roomId: string;
}

export function IdentityViewer({ roomId }: IdentityViewerProps) {
  const [identity, setIdentity] = useState<IdentityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.getIdentity(roomId)
      .then((data) => setIdentity(data as IdentityData))
      .catch(() => setIdentity(null))
      .finally(() => setLoading(false));
  }, [roomId]);

  const handleEdit = () => {
    if (identity) {
      setEditContent(identity.identity_document);
      setEditing(true);
    }
  };

  const handleCancel = () => {
    setEditing(false);
    setEditContent('');
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await api.updateIdentity(roomId, editContent) as IdentityData;
      setIdentity(updated);
      setEditing(false);
    } catch (err) {
      console.error('Failed to save identity:', err);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="identity-viewer">
        <div className="identity-header"><h3>LLM Identity</h3></div>
        <div className="identity-loading">Loading identity...</div>
      </div>
    );
  }

  if (!identity) {
    return (
      <div className="identity-viewer">
        <div className="identity-header"><h3>LLM Identity</h3></div>
        <div className="identity-empty">No identity document yet. The LLM will develop one through conversation.</div>
      </div>
    );
  }

  const updated = new Date(identity.last_updated).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div className="identity-viewer">
      <div className="identity-header">
        <h3>LLM Identity</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          {editing ? (
            <>
              <button className="cancel-btn" onClick={handleCancel}>Cancel</button>
              <button className="save-btn" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </>
          ) : (
            <button className="edit-btn" onClick={handleEdit}>Edit</button>
          )}
        </div>
      </div>

      <div className="identity-meta">
        <span>v{identity.version}</span>
        <span>Updated {updated}</span>
      </div>

      {editing ? (
        <textarea
          className="identity-editor"
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
        />
      ) : (
        <div className="identity-content">{identity.identity_document}</div>
      )}
    </div>
  );
}
