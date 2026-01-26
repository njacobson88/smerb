// UserManagement.js - Admin User Management Page

import React, { useState, useEffect, useCallback } from 'react';
import { UserPlus, Trash2, Shield, User, Loader2, AlertCircle, Phone, Bell } from 'lucide-react';
import { API_BASE_URL, authFetch } from './SocialScope';

const UserManagement = ({ currentUser }) => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isAdmin, setIsAdmin] = useState(false);

  // Add user form state
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState('user');
  const [addingUser, setAddingUser] = useState(false);
  const [addError, setAddError] = useState(null);
  const [addSuccess, setAddSuccess] = useState(null);

  // Safety alert recipients state
  const [alertRecipients, setAlertRecipients] = useState([]);
  const [newPhone, setNewPhone] = useState('');
  const [newPhoneName, setNewPhoneName] = useState('');
  const [addingPhone, setAddingPhone] = useState(false);
  const [phoneError, setPhoneError] = useState(null);
  const [phoneSuccess, setPhoneSuccess] = useState(null);

  // Fetch users
  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/users`);

      if (response.status === 403) {
        setIsAdmin(false);
        setError('You do not have admin access to manage users.');
        return;
      }

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to load users');
      }

      const data = await response.json();
      setUsers(data.users || []);
      setIsAdmin(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch alert recipients
  const fetchAlertRecipients = useCallback(async () => {
    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/alert-recipients`);
      if (response.ok) {
        const data = await response.json();
        setAlertRecipients(data.recipients || []);
      }
    } catch (err) {
      console.error('Error fetching alert recipients:', err);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
    fetchAlertRecipients();
  }, [fetchUsers, fetchAlertRecipients]);

  // Add alert recipient
  const handleAddRecipient = async (e) => {
    e.preventDefault();
    setAddingPhone(true);
    setPhoneError(null);
    setPhoneSuccess(null);

    // Validate phone number (10 digits)
    const cleanPhone = newPhone.replace(/\D/g, '');
    if (cleanPhone.length !== 10) {
      setPhoneError('Please enter a valid 10-digit US phone number');
      setAddingPhone(false);
      return;
    }

    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/alert-recipients`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: cleanPhone, name: newPhoneName }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to add recipient');
      }

      setPhoneSuccess(`Added ${newPhoneName || cleanPhone} to alert recipients`);
      setNewPhone('');
      setNewPhoneName('');
      fetchAlertRecipients();
    } catch (err) {
      setPhoneError(err.message);
    } finally {
      setAddingPhone(false);
    }
  };

  // Remove alert recipient
  const handleRemoveRecipient = async (phone) => {
    if (!window.confirm('Remove this phone number from safety alert recipients?')) {
      return;
    }

    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/alert-recipients/${phone}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to remove recipient');
      }

      fetchAlertRecipients();
    } catch (err) {
      setPhoneError(err.message);
    }
  };

  // Add new user
  const handleAddUser = async (e) => {
    e.preventDefault();
    setAddingUser(true);
    setAddError(null);
    setAddSuccess(null);

    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: newEmail, role: newRole }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to add user');
      }

      setAddSuccess(`Successfully added ${newEmail} as ${newRole}`);
      setNewEmail('');
      setNewRole('user');
      fetchUsers();
    } catch (err) {
      setAddError(err.message);
    } finally {
      setAddingUser(false);
    }
  };

  // Update user role
  const handleUpdateRole = async (email, newRole) => {
    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(email)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to update role');
      }

      fetchUsers();
    } catch (err) {
      setError(err.message);
    }
  };

  // Remove user
  const handleRemoveUser = async (email) => {
    if (!window.confirm(`Are you sure you want to remove ${email}?`)) {
      return;
    }

    try {
      const response = await authFetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(email)}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to remove user');
      }

      fetchUsers();
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="animate-spin text-blue-500 mr-3" size={32} />
        <span className="text-gray-600">Loading user management...</span>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
        <AlertCircle className="mx-auto text-yellow-500 mb-3" size={48} />
        <h2 className="text-xl font-semibold text-yellow-800 mb-2">Access Denied</h2>
        <p className="text-yellow-700">
          You do not have admin privileges to manage users.
          <br />
          Contact an administrator if you need access.
        </p>
      </div>
    );
  }

  return (
    <div className="user-management">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-800 mb-2">User Management</h1>
        <p className="text-gray-600">Manage dashboard access and user roles</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Add User Form */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-4 flex items-center">
          <UserPlus size={20} className="mr-2" />
          Add New User
        </h2>

        <form onSubmit={handleAddUser} className="flex flex-wrap gap-4">
          <div className="flex-1 min-w-64">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Email Address
            </label>
            <input
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="user@dartmouth.edu"
              required
              disabled={addingUser}
            />
          </div>

          <div className="w-48">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Role
            </label>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              disabled={addingUser}
            >
              <option value="user">User (View Only)</option>
              <option value="admin">Admin (Full Access)</option>
            </select>
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={addingUser || !newEmail}
              className="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {addingUser ? 'Adding...' : 'Add User'}
            </button>
          </div>
        </form>

        {addError && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
            {addError}
          </div>
        )}

        {addSuccess && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">
            {addSuccess}
          </div>
        )}
      </div>

      {/* User List */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b bg-gray-50">
          <h2 className="text-lg font-semibold text-gray-800">
            Authorized Users ({users.length})
          </h2>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-6 py-3 text-left text-sm font-semibold text-gray-600">Email</th>
                <th className="px-6 py-3 text-center text-sm font-semibold text-gray-600">Role</th>
                <th className="px-6 py-3 text-center text-sm font-semibold text-gray-600">Added</th>
                <th className="px-6 py-3 text-center text-sm font-semibold text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((user) => (
                <tr key={user.email} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="flex items-center">
                      {user.role === 'admin' ? (
                        <Shield size={18} className="mr-2 text-purple-500" />
                      ) : (
                        <User size={18} className="mr-2 text-gray-400" />
                      )}
                      <span className="font-medium text-gray-800">{user.email}</span>
                      {user.email === currentUser?.email && (
                        <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full">
                          You
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4 text-center">
                    <select
                      value={user.role}
                      onChange={(e) => handleUpdateRole(user.email, e.target.value)}
                      disabled={user.email === currentUser?.email}
                      className={`border rounded px-2 py-1 text-sm ${
                        user.role === 'admin'
                          ? 'border-purple-200 bg-purple-50 text-purple-700'
                          : 'border-gray-200 bg-gray-50 text-gray-700'
                      } ${user.email === currentUser?.email ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td className="px-6 py-4 text-center text-sm text-gray-500">
                    {user.addedAt ? new Date(user.addedAt).toLocaleDateString() : 'N/A'}
                  </td>
                  <td className="px-6 py-4 text-center">
                    {user.email !== currentUser?.email ? (
                      <button
                        onClick={() => handleRemoveUser(user.email)}
                        className="p-2 text-red-500 hover:bg-red-50 rounded-md transition-colors"
                        title="Remove user"
                      >
                        <Trash2 size={18} />
                      </button>
                    ) : (
                      <span className="text-gray-400 text-sm">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {users.length === 0 && (
          <div className="text-center py-12 text-gray-500">
            No users configured yet. Add users above to grant dashboard access.
          </div>
        )}
      </div>

      {/* Safety Alert Recipients */}
      <div className="bg-white rounded-lg shadow p-6 mb-6 mt-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-2 flex items-center">
          <Bell size={20} className="mr-2 text-red-500" />
          Safety Alert Recipients (SMS)
        </h2>
        <p className="text-gray-600 text-sm mb-4">
          These phone numbers receive SMS alerts within 1-2 minutes when a participant triggers a safety concern during check-in.
        </p>

        <form onSubmit={handleAddRecipient} className="flex flex-wrap gap-4 mb-4">
          <div className="flex-1 min-w-48">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name (optional)
            </label>
            <input
              type="text"
              value={newPhoneName}
              onChange={(e) => setNewPhoneName(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="Dr. Smith"
              disabled={addingPhone}
            />
          </div>

          <div className="w-48">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Phone Number
            </label>
            <input
              type="tel"
              value={newPhone}
              onChange={(e) => setNewPhone(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="(555) 123-4567"
              required
              disabled={addingPhone}
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={addingPhone || !newPhone}
              className="px-6 py-2 bg-red-600 text-white font-medium rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {addingPhone ? 'Adding...' : 'Add Recipient'}
            </button>
          </div>
        </form>

        {phoneError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
            {phoneError}
          </div>
        )}

        {phoneSuccess && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">
            {phoneSuccess}
          </div>
        )}

        {/* Recipients List */}
        {alertRecipients.length > 0 ? (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-sm font-semibold text-gray-600">Name</th>
                  <th className="px-4 py-2 text-left text-sm font-semibold text-gray-600">Phone</th>
                  <th className="px-4 py-2 text-center text-sm font-semibold text-gray-600">Added</th>
                  <th className="px-4 py-2 text-center text-sm font-semibold text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {alertRecipients.map((recipient) => (
                  <tr key={recipient.phone} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="flex items-center">
                        <Phone size={16} className="mr-2 text-gray-400" />
                        <span className="font-medium text-gray-800">
                          {recipient.name || '(No name)'}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {recipient.phone.replace(/(\d{3})(\d{3})(\d{4})/, '($1) $2-$3')}
                    </td>
                    <td className="px-4 py-3 text-center text-sm text-gray-500">
                      {recipient.addedAt ? new Date(recipient.addedAt).toLocaleDateString() : 'N/A'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <button
                        onClick={() => handleRemoveRecipient(recipient.phone)}
                        className="p-2 text-red-500 hover:bg-red-50 rounded-md transition-colors"
                        title="Remove recipient"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-6 text-gray-500 border rounded-lg bg-gray-50">
            <Phone size={24} className="mx-auto mb-2 text-gray-400" />
            No alert recipients configured. Add phone numbers above to receive safety alerts.
          </div>
        )}

        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
          <strong>Note:</strong> Safety alerts are sent via SMS within 1-2 minutes of being triggered.
          Ensure the Cloud Function is deployed and Twilio is configured for alerts to work.
        </div>
      </div>

      {/* Role Explanation */}
      <div className="mt-6 bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
        <h3 className="font-semibold text-gray-800 mb-2">Role Permissions:</h3>
        <ul className="space-y-1">
          <li className="flex items-center">
            <User size={14} className="mr-2 text-gray-400" />
            <strong>User:</strong>&nbsp;Can view participant data, export data
          </li>
          <li className="flex items-center">
            <Shield size={14} className="mr-2 text-purple-500" />
            <strong>Admin:</strong>&nbsp;All user permissions + manage user access
          </li>
        </ul>
      </div>
    </div>
  );
};

export default UserManagement;
