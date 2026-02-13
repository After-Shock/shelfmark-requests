import { FormEvent, useState } from 'react';
import { changePassword } from '../services/api';
import { theme } from '../theme';

interface AccountModalProps {
  isOpen: boolean;
  onClose: () => void;
  onShowToast: (message: string, type: 'success' | 'error' | 'info') => void;
}

export const AccountModal = ({ isOpen, onClose, onShowToast }: AccountModalProps) => {
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (newPassword.length < 4) {
      onShowToast('New password must be at least 4 characters', 'error');
      return;
    }

    if (newPassword !== confirmPassword) {
      onShowToast('New passwords do not match', 'error');
      return;
    }

    setIsLoading(true);
    try {
      const result = await changePassword({
        new_password: newPassword,
      });
      onShowToast(result.message || 'Password changed successfully', 'success');
      setNewPassword('');
      setConfirmPassword('');
      onClose();
    } catch (err) {
      onShowToast(err instanceof Error ? err.message : 'Failed to change password', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    setNewPassword('');
    setConfirmPassword('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
      onClick={handleClose}
    >
      <div
        className="relative rounded-lg shadow-2xl max-w-md w-full border"
        style={{
          backgroundColor: 'var(--bg)',
          borderColor: 'var(--border-muted)',
          maxHeight: '90vh',
          overflow: 'auto',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: 'var(--border-muted)' }}
        >
          <h2 className="text-xl font-semibold">Account Settings</h2>
          <button
            type="button"
            onClick={handleClose}
            className="p-1 hover:opacity-70 transition-opacity"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-6">
          <h3 className="text-lg font-medium mb-4">Set Password</h3>
          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="new-password" className="block text-sm font-medium mb-2">
                New Password
              </label>
              <input
                type="password"
                id="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={isLoading}
                placeholder="Enter new password"
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  backgroundColor: 'var(--input-background, var(--bg-soft))',
                  borderColor: 'var(--border-muted)',
                  color: 'var(--text-color)',
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="mb-6">
              <label htmlFor="confirm-new-password" className="block text-sm font-medium mb-2">
                Confirm Password
              </label>
              <input
                type="password"
                id="confirm-new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={isLoading}
                placeholder="Confirm new password"
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  backgroundColor: 'var(--input-background, var(--bg-soft))',
                  borderColor: 'var(--border-muted)',
                  color: 'var(--text-color)',
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleClose}
                disabled={isLoading}
                className="flex-1 px-4 py-2.5 rounded-lg font-medium transition-colors disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--bg-soft)',
                  color: 'var(--text-color)',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading}
                className="flex-1 px-4 py-2.5 rounded-lg font-medium text-white transition-colors disabled:opacity-50"
                style={{ backgroundColor: theme.button.secondary }}
                onMouseEnter={(e) => !isLoading && (e.currentTarget.style.backgroundColor = theme.button.secondaryHover)}
                onMouseLeave={(e) => !isLoading && (e.currentTarget.style.backgroundColor = theme.button.secondary)}
              >
                {isLoading ? 'Changing...' : 'Change Password'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
