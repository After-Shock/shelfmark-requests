import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { withBasePath } from '../utils/basePath';
import { addLibraryAccount, LibraryService, registerUser } from '../services/api';
import { theme } from '../theme';

interface RegisterPageProps {
  onRegisterComplete: () => void;
  signupServices?: {
    audiobookshelf?: boolean;
    calibre_web?: boolean;
  };
}

interface ServiceOption {
  key: 'audiobookshelf' | 'calibre_web';
  label: string;
  description: string;
}

export const RegisterPage = ({ onRegisterComplete, signupServices }: RegisterPageProps) => {
  const logoUrl = withBasePath('/logo.svg');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [linkOffers, setLinkOffers] = useState<LibraryService[]>([]);
  const [appPasswords, setAppPasswords] = useState<Record<string, string>>({});
  const [linkStatus, setLinkStatus] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [linking, setLinking] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const serviceOptions = getServiceOptions(signupServices);

  const [selectedServices, setSelectedServices] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const option of getServiceOptions(signupServices)) {
      initial[option.key] = false;
    }
    return initial;
  });

  const toggleService = (key: string) => {
    setSelectedServices((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setWarnings([]);

    if (!username.trim()) {
      setError('Username is required');
      return;
    }
    if (!inviteCode.trim()) {
      setError('Invite code is required');
      return;
    }
    if (!email.trim()) {
      setError('Email is required');
      return;
    }
    if (serviceOptions.length > 0 && !serviceOptions.some((o) => selectedServices[o.key])) {
      setError('Select at least one library account to create');
      return;
    }
    if (password.length < 4) {
      setError('Password must be at least 4 characters');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setIsLoading(true);
    try {
      const response = await registerUser({
        username: username.trim(),
        password,
        email: email.trim(),
        invite_code: inviteCode.trim(),
        services: Object.fromEntries(
          serviceOptions.map((o) => [o.key, selectedServices[o.key] !== false]),
        ) as Record<string, boolean>,
      });
      if (response.warnings?.length || response.link_offers?.length) {
        // Registration succeeded, but some library accounts failed or already exist.
        setWarnings(response.warnings || []);
        setLinkOffers(response.link_offers || []);
      } else {
        onRegisterComplete();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setIsLoading(false);
    }
  };

  const inputStyle = {
    backgroundColor: 'var(--input-background)',
    borderColor: 'var(--border-color)',
    color: 'var(--text-color)',
  };

  const linkExisting = async (service: LibraryService) => {
    setLinking(service);
    try {
      await addLibraryAccount({ service, password, app_password: appPasswords[service] || '' });
      setLinkStatus((prev) => ({ ...prev, [service]: { ok: true, message: 'Linked' } }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not link';
      setLinkStatus((prev) => ({ ...prev, [service]: { ok: false, message } }));
    } finally {
      setLinking(null);
    }
  };

  if (warnings.length > 0 || linkOffers.length > 0) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-4 py-8"
        style={{ backgroundColor: 'var(--background-color)', color: 'var(--text-color)' }}
      >
        <div className="w-full max-w-md">
          <div
            className="rounded-lg shadow-2xl p-8 border"
            style={{
              backgroundColor: 'var(--card-background)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-color)',
            }}
          >
            <h1 className="text-2xl font-semibold mb-4">Account Created</h1>
            {warnings.length > 0 && (
              <>
                <p className="text-sm mb-4">
                  Your Shelfmark account is ready. Some library accounts could not be created:
                </p>
                <ul className="text-sm mb-6 list-disc list-inside space-y-1 opacity-80">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </>
            )}
            {linkOffers.length > 0 && (
              <div className="mb-6 space-y-4">
                <p className="text-sm">
                  You already have {linkOffers.map((s) => APP_LABELS[s]).join(' and ')} account
                  {linkOffers.length > 1 ? 's' : ''} named <span className="font-medium">{username.trim()}</span>.
                  Link {linkOffers.length > 1 ? 'them' : 'it'} so one password works everywhere: enter that
                  app&apos;s current password and it will switch to the password you just chose.
                </p>
                {linkOffers.map((service) => {
                  const status = linkStatus[service];
                  if (status?.ok) {
                    return (
                      <p key={service} className="text-sm font-medium" style={{ color: theme.primary.turquoise }}>
                        ✓ {APP_LABELS[service]} linked
                      </p>
                    );
                  }
                  return (
                    <div key={service}>
                      <label htmlFor={`app-pw-${service}`} className="block text-sm font-medium mb-2">
                        Current {APP_LABELS[service]} password
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          id={`app-pw-${service}`}
                          value={appPasswords[service] || ''}
                          onChange={(e) => setAppPasswords((prev) => ({ ...prev, [service]: e.target.value }))}
                          disabled={linking !== null}
                          className="flex-1 min-w-0 px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50"
                          style={{ ...inputStyle, '--tw-ring-color': theme.primary.turquoise } as React.CSSProperties}
                          autoComplete="current-password"
                        />
                        <button
                          type="button"
                          onClick={() => linkExisting(service)}
                          disabled={linking !== null || !appPasswords[service]}
                          className="px-4 rounded-lg font-medium text-white disabled:opacity-50"
                          style={{ backgroundColor: '#7c3aed' }}
                        >
                          {linking === service ? 'Linking...' : 'Link'}
                        </button>
                      </div>
                      {status && !status.ok && <p className="text-sm mt-1 text-red-500">{status.message}</p>}
                    </div>
                  );
                })}
                <p className="text-xs opacity-70">
                  Don&apos;t know it? Skip for now, then use Forgot password? on the sign-in page, or link it later
                  from ☰ → Account → Library Access.
                </p>
              </div>
            )}
            <button
              type="button"
              onClick={onRegisterComplete}
              className="w-full py-2.5 px-4 rounded-lg font-medium text-white transition-colors"
              style={{ backgroundColor: theme.button.secondary }}
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 py-8"
      style={{ backgroundColor: 'var(--background-color)', color: 'var(--text-color)' }}
    >
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src={logoUrl} alt="Logo" className="mx-auto mb-6 w-72 h-72" />
          <h1 className="text-2xl font-semibold">Create Account</h1>
          <p className="text-sm opacity-70 mt-2">Sign up to start requesting books</p>
        </div>
        <div
          className="rounded-lg shadow-2xl p-8 border"
          style={{
            backgroundColor: 'var(--card-background)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-color)',
          }}
        >
          {error && (
            <div className="mb-4 p-3 rounded-lg text-sm bg-red-600 text-white">
              {error}
            </div>
          )}
          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="username" className="block text-sm font-medium mb-2">
                Username
              </label>
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  ...inputStyle,
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                autoFocus
                autoCapitalize="none"
                autoCorrect="off"
                required
              />
            </div>

            <div className="mb-4">
              <label htmlFor="email" className="block text-sm font-medium mb-2">
                Email
              </label>
              <input
                type="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  ...inputStyle,
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                placeholder="you@example.com"
                required
              />
            </div>

            <div className="mb-4">
              <label htmlFor="invite-code" className="block text-sm font-medium mb-2">
                Invite Code
              </label>
              <input
                type="text"
                id="invite-code"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  ...inputStyle,
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                autoCapitalize="none"
                autoCorrect="off"
                required
              />
            </div>

            <div className="mb-4">
              <label htmlFor="password" className="block text-sm font-medium mb-2">
                Password
              </label>
              <input
                type="password"
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  ...inputStyle,
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="mb-4">
              <label htmlFor="confirm-password" className="block text-sm font-medium mb-2">
                Confirm Password
              </label>
              <input
                type="password"
                id="confirm-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
                style={{
                  ...inputStyle,
                  '--tw-ring-color': theme.primary.turquoise,
                } as React.CSSProperties}
                autoComplete="new-password"
                required
              />
            </div>

            {serviceOptions.length > 0 && (
              <div className="mb-6">
                <span className="block text-sm font-medium mb-2">
                  Choose library accounts to create
                </span>
                <div className="flex gap-2">
                  {serviceOptions.map((option) => {
                    const isSelected = selectedServices[option.key] !== false;
                    return (
                      <button
                        key={option.key}
                        type="button"
                        onClick={() => toggleService(option.key)}
                        disabled={isLoading}
                        aria-pressed={isSelected}
                        className="flex-1 py-2 px-3 rounded-lg border text-sm transition-colors disabled:opacity-50"
                        style={{
                          backgroundColor: isSelected
                            ? '#7c3aed'
                            : 'var(--input-background)',
                          borderColor: isSelected ? '#7c3aed' : 'var(--border-color)',
                          color: isSelected ? '#ffffff' : 'var(--text-color)',
                          opacity: isSelected ? 1 : 0.7,
                        }}
                      >
                        <span className="block font-medium">{option.label}</span>
                        <span className="block text-xs opacity-80">{option.description}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-lg font-medium text-white transition-colors disabled:opacity-50"
              style={{ backgroundColor: theme.button.secondary }}
              onMouseEnter={(e) => !isLoading && (e.currentTarget.style.backgroundColor = theme.button.secondaryHover)}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = theme.button.secondary)}
            >
              {isLoading ? 'Creating Account...' : 'Create Account'}
            </button>
          </form>

          <p className="text-center text-sm mt-4 opacity-70">
            Already have an account?{' '}
            <Link
              to="/login"
              className="font-medium hover:opacity-80 transition-opacity"
              style={{ color: theme.primary.turquoise }}
            >
              Sign In
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

const APP_LABELS: Record<LibraryService, string> = { calibre_web: 'Ebooks', audiobookshelf: 'Audiobooks' };

function getServiceOptions(
  signupServices?: {
    audiobookshelf?: boolean;
    calibre_web?: boolean;
  },
): ServiceOption[] {
  const options: ServiceOption[] = [];
  if (signupServices?.audiobookshelf) {
    options.push({
      key: 'audiobookshelf',
      label: 'Audiobooks',
      description: 'Listen to audiobooks',
    });
  }
  if (signupServices?.calibre_web) {
    options.push({
      key: 'calibre_web',
      label: 'Ebooks',
      description: 'Read ebooks',
    });
  }
  return options;
}