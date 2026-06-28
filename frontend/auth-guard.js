(function() {
    // 1. Determine active page and session role
    const path = window.location.pathname;
    const page = path.substring(path.lastIndexOf('/') + 1) || 'index.html';
    const role = localStorage.getItem('hero_user_role');

    // Bypass check for login.html
    if (page === 'login.html') {
        // If user already has a session, clear it to act as clean slate or logout
        if (role) {
            localStorage.removeItem('hero_user_role');
        }
        return;
    }

    // 2. Require active session on all portal pages (index.html is the landing page and is open)
    if (!role && page !== 'login.html' && page !== 'index.html') {
        window.location.href = 'login.html';
        return;
    }

    // 3. Enforce route authorization rules
    let authorized = true;
    let returnUrl = 'citizen.html';
    let returnText = 'Return to Citizen Dashboard';

    if (page === 'manager.html') {
        if (role !== 'manager' && role !== 'admin') {
            authorized = false;
        }
    } else if (page === 'admin.html') {
        if (role !== 'admin') {
            authorized = false;
            if (role === 'manager') {
                returnUrl = 'manager.html';
                returnText = 'Return to Manager Dashboard';
            }
        }
    }

    if (!authorized) {
        // Hide document rendering instantly to prevent flashes of sensitive data
        document.documentElement.style.display = 'none';

        document.addEventListener('DOMContentLoaded', () => {
            // Restore visibility and inject Access Restricted screen
            document.documentElement.style.display = 'block';
            document.title = 'Access Restricted — Community Helper';
            
            // Apply a consistent clean dark backdrop style directly
            document.body.className = 'bg-slate-950 text-white min-h-screen flex flex-col justify-center items-center p-6 relative overflow-hidden font-sans';
            document.body.innerHTML = `
                <!-- Background Grids & Blobs -->
                <div class="absolute inset-0 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:40px_40px] opacity-10 pointer-events-none z-0"></div>
                <div class="absolute top-[-10%] right-[-10%] w-[50vw] h-[50vw] bg-red-950/20 rounded-full blur-3xl pointer-events-none z-0"></div>
                
                <div class="max-w-md w-full bg-slate-900/80 backdrop-blur-md border border-red-500/20 rounded-3xl p-8 text-center shadow-2xl relative z-10 space-y-6">
                    <div class="w-16 h-16 bg-red-500/10 border border-red-500/30 rounded-2xl flex items-center justify-center mx-auto text-red-500">
                        <span class="material-symbols-outlined text-3xl font-bold">gpp_bad</span>
                    </div>
                    
                    <div class="space-y-2">
                        <h2 class="text-xl font-black tracking-tight text-red-400">Security Clearance Required</h2>
                        <p class="text-xs text-slate-500 font-mono tracking-wider uppercase">Access Denied (403)</p>
                    </div>
                    
                    <p class="text-sm text-slate-300 leading-relaxed font-medium">
                        Access Restricted: This portal requires authorized personnel permissions.
                    </p>
                    
                    <div class="pt-4">
                        <a href="${returnUrl}" class="inline-flex items-center justify-center px-6 py-3 bg-red-600 hover:bg-red-500 text-white text-xs font-black uppercase tracking-wider rounded-xl shadow-lg transition-all duration-300 transform hover:-translate-y-0.5">
                            ${returnText}
                        </a>
                    </div>
                </div>
            `;
        });
        
        // Stop downstream JS/CSS evaluations
        window.stop();
        return;
    }

    // 4. Intercept all global fetch calls to inject X-User-Role credentials
    const originalFetch = window.fetch;
    window.fetch = async function(url, options) {
        options = options || {};
        options.headers = options.headers || {};

        // Rewrite API URL dynamically if running in production on Cloud Run
        if (typeof url === 'string' && url.startsWith('http://127.0.0.1:8000')) {
            const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
            if (!isLocal) {
                url = url.replace('http://127.0.0.1:8000', window.location.origin);
            }
        }

        // Inject role header; fall back to 'member' for public pages (e.g. index.html) that
        // read public data without a login session — backend middleware requires any valid role.
        const effectiveRole = role || 'member';
        if (options.headers instanceof Headers) {
            options.headers.set('X-User-Role', effectiveRole);
        } else if (Array.isArray(options.headers)) {
            options.headers.push(['X-User-Role', effectiveRole]);
        } else {
            options.headers['X-User-Role'] = effectiveRole;
        }
        try {
            const response = await originalFetch(url, options);
            if (response.status === 403) {
                const data = await response.clone().json().catch(() => ({}));
                const detail = data.detail || "Access Restricted: Action unauthorized.";
                showGlobalToast(detail, 'error');
            }
            return response;
        } catch (err) {
            throw err;
        }
    };

    // Intercept native WebSocket to support dynamic API URL and rewrite in production
    const originalWebSocket = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        if (typeof url === 'string' && url.startsWith('ws://127.0.0.1:8000')) {
            const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
            if (!isLocal) {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                url = url.replace('ws://127.0.0.1:8000', `${protocol}//${window.location.host}`);
            }
        }
        return new originalWebSocket(url, protocols);
    };

    // 5. Dynamic navigation filter and header elements insertion
    document.addEventListener('DOMContentLoaded', () => {
        // Handle anonymous state for landing page
        if (!role) {
            // Remove Citizen, Manager, Administrator switcher links if anonymous
            document.querySelectorAll('header a[href*="report.html"]').forEach(el => el.remove());
            document.querySelectorAll('header a[href*="manager.html"]').forEach(el => el.remove());
            document.querySelectorAll('header a[href*="admin.html"]').forEach(el => el.remove());
            
            // Add Sign In and Sign Up buttons — always inject into a dedicated container on the header
            const header = document.querySelector('header');
            if (header && page !== 'login.html' && !header.querySelector('.sign-in-btn')) {
                const authContainer = document.createElement('div');
                authContainer.style.cssText = 'display:flex;align-items:center;gap:10px;position:relative;z-index:100;pointer-events:auto;margin-left:auto;flex-shrink:0;';
                authContainer.innerHTML = `
                    <a href="login.html" class="sign-in-btn" style="display:inline-flex;align-items:center;padding:6px 12px;font-size:11px;font-weight:700;color:#374151;background:#fff;border:1px solid #e2e8f0;border-radius:8px;text-decoration:none;text-transform:uppercase;letter-spacing:0.05em;box-shadow:0 1px 3px rgba(0,0,0,0.08);pointer-events:auto;cursor:pointer;">Sign In</a>
                    <a href="login.html?tab=signup" class="sign-up-btn" style="display:inline-flex;align-items:center;padding:6px 12px;font-size:11px;font-weight:700;color:#fff;background:#FF6B35;border-radius:8px;text-decoration:none;text-transform:uppercase;letter-spacing:0.05em;pointer-events:auto;cursor:pointer;">Sign Up</a>
                `;
                header.style.position = header.style.position || 'sticky';
                header.appendChild(authContainer);
            }
            return;
        }

        // Remove unauthorized tabs for logged in users
        if (role !== 'manager' && role !== 'admin') {
            document.querySelectorAll('header a[href*="manager.html"]').forEach(el => el.remove());
        }
        if (role !== 'admin') {
            document.querySelectorAll('header a[href*="admin.html"]').forEach(el => el.remove());
        }

        // Add user info and auth buttons to page headers
        const header = document.querySelector('header');
        if (header && page !== 'login.html') {
            let rightContainer = header.querySelector('.flex.items-center.gap-4') || header.querySelector('.flex.items-center.gap-6:last-child') || header.querySelector('.flex.items-center:last-child');
            
            if (!rightContainer || rightContainer === header.firstElementChild) {
                rightContainer = document.createElement('div');
                rightContainer.className = 'flex items-center gap-4';
                header.appendChild(rightContainer);
            }

            const roleDisplay = {
                member: 'Citizen',
                manager: 'Manager',
                admin: 'Administrator'
            };
            const roleColorClass = {
                member: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-700',
                manager: 'bg-blue-500/10 border-blue-500/20 text-blue-700',
                admin: 'bg-indigo-500/10 border-indigo-500/20 text-indigo-700'
            };

            const activeRoleName = roleDisplay[role] || role;
            const badgeClass = roleColorClass[role] || 'bg-slate-500/10 border-slate-500/20 text-slate-700';

            const sessionDiv = document.createElement('div');
            sessionDiv.className = 'flex items-center gap-2.5 ml-2 z-[99]';
            sessionDiv.innerHTML = `
                <span class="hidden sm:inline-flex font-mono-ui text-[9px] font-bold px-2.5 py-1 rounded-full border ${badgeClass} uppercase tracking-wider">
                    ${activeRoleName}
                </span>
                <button onclick="logoutUser()" class="px-3 py-1.5 text-xs font-bold text-slate-700 bg-white hover:bg-red-50 hover:text-red-600 hover:border-red-200 border border-slate-200 rounded-lg transition-colors uppercase tracking-wider shadow-sm flex items-center gap-1.5">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                    Logout
                </button>
            `;

            // Position dynamically before profile image or at the end
            if (rightContainer.lastElementChild && rightContainer.lastElementChild.tagName === 'IMG') {
                rightContainer.insertBefore(sessionDiv, rightContainer.lastElementChild);
            } else {
                rightContainer.appendChild(sessionDiv);
            }
        }
    });

    // Logout controller — clears all auth state and returns to simulator
    window.logoutUser = function() {
        const keysToRemove = [
            'hero_user_role', 'hero_user_email', 'hero_user_token',
            'hero_incidents_list', 'hero_session'
        ];
        keysToRemove.forEach(k => localStorage.removeItem(k));
        // Clear any points/notif caches keyed by email
        const email = localStorage.getItem('hero_user_email') || '';
        if (email) {
            localStorage.removeItem(`hero_notifs_${email}`);
            localStorage.removeItem(`hero_points_${email}`);
        }
        sessionStorage.clear();
        window.location.href = 'index.html';
    };

    // Shared global Toast constructor
    function showGlobalToast(message, type = 'error') {
        let toastContainer = document.getElementById('global-toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'global-toast-container';
            toastContainer.className = 'fixed top-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm pointer-events-none';
            document.body.appendChild(toastContainer);
        }
        
        const toast = document.createElement('div');
        toast.className = `px-4 py-3 rounded-xl shadow-2xl text-[11px] font-semibold text-white border pointer-events-auto transition-all duration-300 transform translate-x-12 opacity-0 flex items-center gap-2 ${
            type === 'error' ? 'bg-slate-900/95 border-red-500/30 text-red-200' : 'bg-slate-900/95 border-emerald-500/30 text-emerald-200'
        }`;
        
        const icon = document.createElement('span');
        icon.className = 'material-symbols-outlined text-sm ' + (type === 'error' ? 'text-red-400' : 'text-emerald-400');
        icon.textContent = type === 'error' ? 'gpp_bad' : 'check_circle';
        
        const text = document.createElement('span');
        text.textContent = message;
        
        toast.appendChild(icon);
        toast.appendChild(text);
        toastContainer.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.remove('translate-x-12', 'opacity-0');
            toast.classList.add('translate-x-0', 'opacity-100');
        }, 10);
        
        setTimeout(() => {
            toast.classList.remove('translate-x-0', 'opacity-100');
            toast.classList.add('translate-x-12', 'opacity-0');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }
})();
