// Modern SMS Hub Frontend JavaScript

class SMSApp {
    constructor() {
        this.apiBase = '/api';
        this.currentStep = 1;
        this.csvData = null;
        this.currentPage = 1;
        this.pageSize = 20;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.checkConfiguration();
        this.updatePageTitle('Configuration');

        // Auto-refresh data every 30 seconds
        setInterval(() => {
            if (this.isConfigured()) {
                this.loadStats();
                this.loadBulkJobs();
            }
        }, 30000);
    }

    isConfigured() {
        const statusDot = document.getElementById('config-status-dot');
        return statusDot && statusDot.classList.contains('connected');
    }

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('.nav-item').forEach(button => {
            button.addEventListener('click', (e) => {
                const tab = e.currentTarget.dataset.tab;
                if (tab && !e.currentTarget.classList.contains('disabled')) {
                    this.switchTab(tab);
                }
            });
        });

        // Configuration form
        document.getElementById('config-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveConfiguration();
        });

        // Test configuration button
        document.getElementById('test-config').addEventListener('click', () => {
            this.testConfiguration();
        });

        // Sender type radio buttons
        document.querySelectorAll('input[name="sender-type"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                this.toggleSenderInput(e.target.value);
            });
        });

        // Password toggle
        document.querySelectorAll('.toggle-password').forEach(button => {
            button.addEventListener('click', (e) => {
                this.togglePasswordVisibility(e.target);
            });
        });

        // Send SMS form
        const sendForm = document.getElementById('send-sms-form');
        if (sendForm) {
            sendForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.sendSMS();
            });
        }

        // Phone number validation
        const phoneInput = document.getElementById('phone-number');
        if (phoneInput) {
            phoneInput.addEventListener('input', (e) => {
                this.validatePhoneNumber(e.target);
            });
        }

        // Message body character counter
        const messageBody = document.getElementById('message-body');
        if (messageBody) {
            messageBody.addEventListener('input', (e) => {
                this.updateCharCount(e.target, 'char-count', 'segment-count');
            });
        }

        // Clear form button
        const clearButton = document.getElementById('clear-form');
        if (clearButton) {
            clearButton.addEventListener('click', () => {
                this.clearSendForm();
            });
        }

        // Bulk SMS form
        const bulkForm = document.getElementById('bulk-sms-form');
        if (bulkForm) {
            bulkForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.sendBulkSMS();
            });
        }

        // History controls
        this.setupHistoryListeners();

        // Global refresh button
        const refreshButton = document.getElementById('refresh-data');
        if (refreshButton) {
            refreshButton.addEventListener('click', () => {
                this.refreshCurrentTab();
            });
        }
    }

    switchTab(tabName) {
        // Update navigation
        document.querySelectorAll('.nav-item').forEach(button => {
            button.classList.remove('active');
        });
        const activeButton = document.querySelector(`[data-tab="${tabName}"]`);
        if (activeButton) {
            activeButton.classList.add('active');
        }

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        const activeContent = document.getElementById(tabName);
        if (activeContent) {
            activeContent.classList.add('active');
        }

        // Update page title
        this.updatePageTitle(this.getTabTitle(tabName));

        // Load data for specific tabs
        if (tabName === 'config') {
            this.checkConfiguration();
        } else if (tabName === 'history') {
            this.loadHistory();
        } else if (tabName === 'stats') {
            this.loadStats();
        } else if (tabName === 'bulk-sms') {
            this.loadBulkJobs();
        }
    }

    updatePageTitle(title) {
        const pageTitle = document.getElementById('page-title');
        if (pageTitle) {
            pageTitle.textContent = title;
        }
    }

    getTabTitle(tabName) {
        const titles = {
            'config': 'Configuration',
            'send-sms': 'Send SMS',
            'bulk-sms': 'Bulk SMS Campaign',
            'history': 'Message History',
            'stats': 'SMS Analytics'
        };
        return titles[tabName] || 'SMS Hub';
    }

    toggleSenderInput(senderType) {
        const phoneGroup = document.getElementById('phone-number-group');
        const senderIdGroup = document.getElementById('sender-id-group');

        if (senderType === 'phone') {
            phoneGroup.style.display = 'block';
            senderIdGroup.style.display = 'none';
            document.getElementById('phone-number-config').required = true;
            document.getElementById('sender-id-config').required = false;
        } else {
            phoneGroup.style.display = 'none';
            senderIdGroup.style.display = 'block';
            document.getElementById('phone-number-config').required = false;
            document.getElementById('sender-id-config').required = true;
        }
    }

    togglePasswordVisibility(button) {
        const targetId = button.dataset.target;
        const input = document.getElementById(targetId);
        const icon = button.querySelector('i');

        if (input.type === 'password') {
            input.type = 'text';
            icon.className = 'fas fa-eye-slash';
        } else {
            input.type = 'password';
            icon.className = 'fas fa-eye';
        }
    }

    validatePhoneNumber(input) {
        const container = input.parentElement;
        const value = input.value.trim();

        // Simple validation - starts with + and has at least 10 digits
        const isValid = /^\+\d{10,15}$/.test(value);

        container.classList.remove('valid', 'invalid');
        if (value.length > 0) {
            container.classList.add(isValid ? 'valid' : 'invalid');
        }

        return isValid;
    }

    clearSendForm() {
        document.getElementById('send-sms-form').reset();
        document.getElementById('char-count').textContent = '0';
        document.getElementById('segment-count').textContent = '1 segment';

        // Clear validation states
        const phoneContainer = document.querySelector('.input-with-validation');
        if (phoneContainer) {
            phoneContainer.classList.remove('valid', 'invalid');
        }
    }

    refreshCurrentTab() {
        const activeTab = document.querySelector('.nav-item.active');
        if (activeTab) {
            const tabName = activeTab.dataset.tab;
            this.switchTab(tabName);
        }
    }

    updateCharCount(textarea, charCountId, segmentCountId) {
        const charCount = textarea.value.length;
        const maxLength = textarea.getAttribute('maxlength') || 1600;

        // Update character count
        const charCountElement = document.getElementById(charCountId);
        if (charCountElement) {
            charCountElement.textContent = charCount;

            // Change color based on usage
            const parent = charCountElement.parentElement;
            if (charCount > maxLength * 0.9) {
                parent.style.color = 'var(--error-color)';
            } else if (charCount > maxLength * 0.7) {
                parent.style.color = 'var(--warning-color)';
            } else {
                parent.style.color = 'var(--text-muted)';
            }
        }

        // Update segment count
        if (segmentCountId) {
            const segmentCountElement = document.getElementById(segmentCountId);
            if (segmentCountElement) {
                const segments = this.calculateSMSSegments(textarea.value);
                segmentCountElement.textContent = `${segments} segment${segments !== 1 ? 's' : ''}`;
            }
        }
    }

    calculateSMSSegments(text) {
        if (!text) return 1;

        // Basic SMS segment calculation
        // Single segment: 160 characters for GSM 7-bit, 70 for UCS-2
        // Multi-segment: 153 characters for GSM 7-bit, 67 for UCS-2

        const hasUnicode = /[^\x00-\x7F]/.test(text);
        const singleSegmentLimit = hasUnicode ? 70 : 160;
        const multiSegmentLimit = hasUnicode ? 67 : 153;

        if (text.length <= singleSegmentLimit) {
            return 1;
        }

        return Math.ceil(text.length / multiSegmentLimit);
    }

    showLoading() {
        document.getElementById('loading-overlay').style.display = 'flex';
    }

    hideLoading() {
        document.getElementById('loading-overlay').style.display = 'none';
    }

    showResult(elementId, message, isSuccess = true) {
        const resultElement = document.getElementById(elementId);
        resultElement.textContent = message;
        resultElement.className = `result-message ${isSuccess ? 'success' : 'error'}`;
        resultElement.style.display = 'block';

        // Hide after 5 seconds
        setTimeout(() => {
            resultElement.style.display = 'none';
        }, 5000);
    }

    showAlert(elementId, message, type = 'info') {
        const alertElement = document.getElementById(elementId);
        if (alertElement) {
            alertElement.innerHTML = `
                <div class="alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show" role="alert">
                    ${message}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            `;
            alertElement.style.display = 'block';

            // Auto-hide after 5 seconds
            setTimeout(() => {
                const alert = alertElement.querySelector('.alert');
                if (alert) {
                    alert.classList.remove('show');
                    setTimeout(() => {
                        alertElement.innerHTML = '';
                        alertElement.style.display = 'none';
                    }, 150);
                }
            }, 5000);
        }
    }

    async checkConfiguration() {
        try {
            const response = await fetch(`${this.apiBase}/config/status`);
            const result = await response.json();

            const statusElement = document.getElementById('config-status');
            const statusIcon = document.getElementById('status-icon');
            const statusText = document.getElementById('status-text');

            if (result.configured) {
                statusElement.className = 'config-status connected';
                statusIcon.className = 'fas fa-check-circle';
                statusText.textContent = 'Twilio configuration is valid and connected';

                // Load current configuration
                if (result.config) {
                    document.getElementById('account-sid').value = result.config.account_sid || '';
                    document.getElementById('phone-number-config').value = result.config.phone_number || '';
                    // Don't populate auth token for security
                }

                // Enable other tabs
                this.enableTabs();

                // Load initial data
                this.loadAccountBalance();
                this.loadStats();
                this.loadHistory();
                this.loadBulkJobs();
            } else {
                statusElement.className = 'config-status error';
                statusIcon.className = 'fas fa-exclamation-circle';
                statusText.textContent = result.message || 'Twilio configuration required';

                // Disable other tabs
                this.disableTabs();
            }
        } catch (error) {
            const statusElement = document.getElementById('config-status');
            const statusIcon = document.getElementById('status-icon');
            const statusText = document.getElementById('status-text');

            statusElement.className = 'config-status error';
            statusIcon.className = 'fas fa-exclamation-circle';
            statusText.textContent = 'Error checking configuration';
        }
    }

    enableTabs() {
        document.querySelectorAll('.tab-button').forEach(button => {
            if (button.dataset.tab !== 'config') {
                button.disabled = false;
                button.style.opacity = '1';
                button.style.pointerEvents = 'auto';
            }
        });
    }

    disableTabs() {
        document.querySelectorAll('.tab-button').forEach(button => {
            if (button.dataset.tab !== 'config') {
                button.disabled = true;
                button.style.opacity = '0.5';
                button.style.pointerEvents = 'none';
            }
        });
    }

    async saveConfiguration() {
        const accountSid = document.getElementById('account-sid').value;
        const authToken = document.getElementById('auth-token').value;
        const senderType = document.querySelector('input[name="sender-type"]:checked').value;

        let senderValue = '';
        if (senderType === 'phone') {
            senderValue = document.getElementById('phone-number-config').value;
        } else {
            senderValue = document.getElementById('sender-id-config').value;
        }

        if (!accountSid || !authToken || !senderValue) {
            this.showAlert('config-result', 'Please fill in all required fields', 'error');
            return;
        }

        this.showLoading();

        try {
            const configData = {
                account_sid: accountSid,
                auth_token: authToken,
                sender_type: senderType
            };

            if (senderType === 'phone') {
                configData.phone_number = senderValue;
            } else {
                configData.sender_id = senderValue;
            }

            const response = await fetch(`${this.apiBase}/config/save`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(configData)
            });

            const result = await response.json();

            if (result.success) {
                this.showAlert('config-result', 'Configuration saved successfully!', 'success');

                // Clear auth token field for security
                document.getElementById('auth-token').value = '';

                // Recheck configuration
                setTimeout(() => {
                    this.checkConfiguration();
                }, 1000);
            } else {
                this.showAlert('config-result', `Failed to save configuration: ${result.message}`, 'error');
            }
        } catch (error) {
            this.showAlert('config-result', `Error: ${error.message}`, 'error');
        } finally {
            this.hideLoading();
        }
    }

    async testConfiguration() {
        const accountSid = document.getElementById('account-sid').value;
        const authToken = document.getElementById('auth-token').value;
        const senderType = document.querySelector('input[name="sender-type"]:checked').value;

        let senderValue = '';
        if (senderType === 'phone') {
            senderValue = document.getElementById('phone-number-config').value;
        } else {
            senderValue = document.getElementById('sender-id-config').value;
        }

        if (!accountSid || !authToken || !senderValue) {
            this.showAlert('config-result', 'Please fill in all required fields before testing', 'error');
            return;
        }

        this.showLoading();

        try {
            const configData = {
                account_sid: accountSid,
                auth_token: authToken,
                sender_type: senderType
            };

            if (senderType === 'phone') {
                configData.phone_number = senderValue;
            } else {
                configData.sender_id = senderValue;
            }

            const response = await fetch(`${this.apiBase}/config/test`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(configData)
            });

            const result = await response.json();

            if (result.success) {
                this.showAlert('config-result',
                    `Connection test successful! Account balance: ${result.balance} ${result.currency}`,
                    'success');
            } else {
                this.showAlert('config-result',
                    `Connection test failed: ${result.message}`,
                    'error');
            }
        } catch (error) {
            this.showAlert('config-result', `Error testing connection: ${error.message}`, 'error');
        } finally {
            this.hideLoading();
        }
    }

    async sendSMS() {
        const phoneNumber = document.getElementById('phone-number').value;
        const messageBody = document.getElementById('message-body').value;

        if (!phoneNumber || !messageBody) {
            this.showResult('send-result', 'Please fill in all fields', false);
            return;
        }

        this.showLoading();

        try {
            const response = await fetch(`${this.apiBase}/sms/send`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    to_number: phoneNumber,
                    message_body: messageBody
                })
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }

            const result = await response.json();

            if (result.success) {
                this.showResult('send-result',
                    `SMS sent successfully! Message SID: ${result.message_sid}${result.cost ? ` (Cost: $${result.cost})` : ''}`,
                    true);

                // Clear form
                document.getElementById('send-sms-form').reset();
                const charCountElement = document.getElementById('char-count');
                if (charCountElement) {
                    charCountElement.textContent = '0';
                }

                // Refresh stats and history
                this.loadStats();
                this.loadHistory();
            } else {
                const errorMessage = result.message || result.detail || result.error_message || 'Unknown error occurred';
                this.showResult('send-result', `Failed to send SMS: ${errorMessage}`, false);
            }
        } catch (error) {
            this.showResult('send-result', `Error: ${error.message}`, false);
        } finally {
            this.hideLoading();
        }
    }

    async sendBulkSMS() {
        const fileInput = document.getElementById('csv-file');
        const messageTemplate = document.getElementById('message-template').value;

        if (!fileInput.files[0] || !messageTemplate) {
            this.showResult('bulk-result', 'Please select a CSV file and enter a message template', false);
            return;
        }

        this.showLoading();

        try {
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('message_template', messageTemplate);

            const response = await fetch(`${this.apiBase}/sms/bulk`, {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                this.showResult('bulk-result', 
                    `Bulk SMS job started! Job ID: ${result.job_id}. Processing ${result.total_count} messages.`, 
                    true);
                
                // Clear form
                document.getElementById('bulk-sms-form').reset();
                
                // Refresh bulk jobs
                this.loadBulkJobs();
            } else {
                this.showResult('bulk-result', `Failed to start bulk SMS: ${result.message}`, false);
            }
        } catch (error) {
            this.showResult('bulk-result', `Error: ${error.message}`, false);
        } finally {
            this.hideLoading();
        }
    }

    async loadAccountBalance() {
        try {
            const response = await fetch(`${this.apiBase}/account/balance`);
            const result = await response.json();

            if (result.success) {
                document.getElementById('account-balance').textContent = 
                    `Balance: ${result.currency} ${result.balance}`;
            } else {
                document.getElementById('account-balance').textContent = 'Balance: N/A';
            }
        } catch (error) {
            document.getElementById('account-balance').textContent = 'Balance: Error';
        }
    }

    async loadStats() {
        try {
            const response = await fetch(`${this.apiBase}/sms/stats`);
            const stats = await response.json();

            document.getElementById('total-sent').textContent = stats.total_sent;
            document.getElementById('total-delivered').textContent = stats.total_delivered;
            document.getElementById('total-failed').textContent = stats.total_failed;
            document.getElementById('total-cost').textContent = `$${stats.total_cost.toFixed(2)}`;
            document.getElementById('today-sent').textContent = stats.today_sent;
            document.getElementById('month-sent').textContent = stats.this_month_sent;
        } catch (error) {
            console.error('Error loading stats:', error);
        }
    }

    async loadHistory() {
        try {
            const response = await fetch(`${this.apiBase}/sms/history?limit=50`);
            const history = await response.json();

            const historyContainer = document.getElementById('sms-history');
            
            if (history.length === 0) {
                historyContainer.innerHTML = '<p>No SMS messages found.</p>';
                return;
            }

            historyContainer.innerHTML = history.map(msg => `
                <div class="history-item ${msg.direction} ${msg.status}">
                    <div class="history-meta">
                        <span><strong>${msg.direction === 'outbound' ? 'To' : 'From'}:</strong> ${msg.direction === 'outbound' ? msg.to_number : msg.from_number}</span>
                        <span><strong>Status:</strong> ${msg.status}</span>
                        <span><strong>Date:</strong> ${new Date(msg.created_at).toLocaleString()}</span>
                        ${msg.cost ? `<span><strong>Cost:</strong> $${msg.cost}</span>` : ''}
                    </div>
                    <div class="history-message">${msg.message_body}</div>
                    ${msg.error_message ? `<div style="color: #dc3545; font-size: 0.875rem; margin-top: 5px;">Error: ${msg.error_message}</div>` : ''}
                </div>
            `).join('');
        } catch (error) {
            document.getElementById('sms-history').innerHTML = '<p>Error loading history.</p>';
        }
    }

    async loadBulkJobs() {
        try {
            const response = await fetch(`${this.apiBase}/sms/jobs`);
            const jobs = await response.json();

            const jobsContainer = document.getElementById('bulk-jobs-list');
            
            if (jobs.length === 0) {
                jobsContainer.innerHTML = '<p>No bulk SMS jobs found.</p>';
                return;
            }

            jobsContainer.innerHTML = jobs.map(job => `
                <div class="job-item ${job.status}">
                    <div class="job-meta">
                        <span><strong>File:</strong> ${job.filename}</span>
                        <span><strong>Status:</strong> ${job.status}</span>
                        <span><strong>Created:</strong> ${new Date(job.created_at).toLocaleString()}</span>
                    </div>
                    <div class="job-progress">
                        Progress: ${job.sent_count}/${job.total_count} sent
                        ${job.failed_count > 0 ? `, ${job.failed_count} failed` : ''}
                    </div>
                    <div style="font-size: 0.875rem; color: #666; margin-top: 5px;">
                        Template: ${job.message_template.substring(0, 100)}${job.message_template.length > 100 ? '...' : ''}
                    </div>
                </div>
            `).join('');
        } catch (error) {
            document.getElementById('bulk-jobs-list').innerHTML = '<p>Error loading bulk jobs.</p>';
        }
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new SMSApp();
});
