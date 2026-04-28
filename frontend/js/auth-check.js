/**
 * CampusHub Session Tracker & Auth Guard
 * Prevents unauthorized access and handles role-based redirection.
 */

const AuthGuard = {
    // ⚡️ Cookie-Based Identity Retrieval (Non-sensitive)
    getUser: function() {
        const userStr = localStorage.getItem('user_metadata');
        if (!userStr) return null;
        try {
            return JSON.parse(userStr);
        } catch (e) {
            this.logout();
            return null;
        }
    },

    // 🔄 SECURE FETCH: Handles 401s and auto-refreshes tokens
    secureFetch: async function(url, options = {}) {
        options.credentials = 'include'; // REQUIRED for HTTP-only cookies
        
        let response = await fetch(url, options);
        
        if (response.status === 401) {
            const data = await response.clone().json();
            if (data.code === 'TOKEN_EXPIRED') {
                console.log("🔄 Session expired. Attempting rotation...");
                const refreshRes = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
                
                if (refreshRes.ok) {
                    console.log("✅ Session renewed successfully.");
                    return fetch(url, options); // Retry original request
                } else {
                    console.error("❌ Refresh failed. Identity revoked.");
                    this.notifySessionExpired();
                }
            } else {
                this.notifySessionExpired();
            }
        }
        if (response.status === 403) {
            try {
                const data = await response.clone().json();
                // Only kick out if it's a strict security/auth violation
                if (data.error && (data.error.includes("Session terminated") || data.error.includes("Security violation"))) {
                    this.notifySessionExpired();
                }
            } catch (e) {}
        }
        return response;
    },

    // ⛔ BLOCKS: Guest pages (Sign-In, Sign-Up) if already logged in
    requireGuest: function() {
        const user = this.getUser();
        if (user) {
            this.redirectToDashboard(user.role);
        }
    },

    // 🔒 BLOCKS: Dashboard pages if NOT logged in or role mismatch
    requireAuth: function(allowedRoles = []) {
        const user = this.getUser();
        if (!user) {
            window.location.replace('/sign-in.html');
            return;
        }
        
        if (allowedRoles.length > 0 && !allowedRoles.includes(user.role)) {
            this.redirectToDashboard(user.role);
        }
    },

    // Redirect to the correct home based on role
    redirectToDashboard: function(role) {
        if (role === 'admin') window.location.replace('/dashboard/admin.html');
        else if (role === 'organizer') window.location.replace('/dashboard/organizer.html');
        else window.location.replace('/dashboard/student.html');
    },

    // Session Clear & Logout
    logout: async function() {
        try {
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
        } catch (e) {}
        this.clearAndRedirect();
    },

    clearAndRedirect: function() {
        localStorage.clear();
        sessionStorage.clear();
        window.location.replace('/sign-in.html');
    },

    // 📢 NOTIFY: Alert user before kicking them out
    notifySessionExpired: function() {
        if (window.isSessionAlerting) return;
        window.isSessionAlerting = true;

        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Session Expired',
                text: 'Your security token has expired or is invalid. Please sign in again to continue.',
                icon: 'warning',
                confirmButtonText: 'Return to Sign In',
                confirmButtonColor: '#2563eb',
                allowOutsideClick: false,
                allowEscapeKey: false
            }).then(() => {
                this.clearAndRedirect();
            });
        } else {
            alert("Session expired. Please sign in again.");
            this.clearAndRedirect();
        }
    }
};

/**
 * BRUTAL BFCache Fix:
 * Modern browsers like Safari/Chrome sometimes keep a snapshot of the page in memory (BFCache).
 * The 'pageshow' event fires when navigating back/forward, even if the script doesn't re-run from scratch.
 * This ensures we re-verify the session EVERY time the page becomes visible.
 */
window.addEventListener('pageshow', function(event) {
    const user = AuthGuard.getUser();
    const path = window.location.pathname;

    // 1. Dashboard Protection
    if (path.includes('/dashboard/')) {
        if (!user) {
            window.location.replace('/sign-in.html');
            return;
        }

        // Strict Role-Path Re-Verification
        const isPathAdmin = path.includes('/admin');
        const isPathOrg = path.includes('/organizer');
        const isPathStudent = path.includes('/student') || path.includes('/profile.html');

        if (isPathAdmin && user.role !== 'admin') {
            AuthGuard.redirectToDashboard(user.role);
        } else if (isPathOrg && user.role !== 'organizer') {
            AuthGuard.redirectToDashboard(user.role);
        } else if (isPathStudent && user.role !== 'student' && user.role !== 'admin' && user.role !== 'organizer') {
            // For general dashboard pages, check if role is valid at all
            AuthGuard.redirectToDashboard(user.role);
        }
    } 
    
    // 2. Auth Page Protection (Prevents going back to login after logging in)
    else if (path.includes('sign-in.html') || path.includes('sign-up.html') || path === '/') {
        if (user) {
            AuthGuard.redirectToDashboard(user.role);
        }
    }
});

// Global Logout Hook for HTML onclicks
function logout() { AuthGuard.logout(); }

