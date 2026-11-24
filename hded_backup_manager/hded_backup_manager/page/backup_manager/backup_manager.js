frappe.pages["backup-manager"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "مدير النسخ الاحتياطي",
        single_column: true,
    });
    new HDEDBBackupManager(wrapper, page);
};

class HDEDBBackupManager {
    constructor(wrapper, page) {
        this.wrapper = $(wrapper);
        this.page = page;
        this.body = $(page.body);
        this.page.set_primary_action("إنشاء نسخة الآن", () => this.startBackup(), "database");
        this.page.set_secondary_action("تحديث", () => this.load(), "refresh");
        this.renderShell();
        this.load();
    }

    icon(name, size = "button") {
        const paths = {
            dashboard: '<rect x="3" y="3" width="8" height="8" rx="1.4"/><rect x="13" y="3" width="8" height="5" rx="1.4"/><rect x="13" y="10" width="8" height="11" rx="1.4"/><rect x="3" y="13" width="8" height="8" rx="1.4"/>',
            settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 1.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.1h-2.6v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1-1.8-1.8.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H6.4v-2.6h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 1.8-1.8.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5v-.1H15v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1 1.8 1.8-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.1v2.6h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
            apps: '<rect x="3" y="3" width="7" height="7" rx="1.4"/><rect x="14" y="3" width="7" height="7" rx="1.4"/><rect x="3" y="14" width="7" height="7" rx="1.4"/><rect x="14" y="14" width="7" height="7" rx="1.4"/>',
            cloud: '<path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 8.5 4.8 4.8 0 0 0 7 18z"/><path d="M12 12v7m-3-3 3 3 3-3"/>',
            mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
            drive: '<path d="m8 3 4 0 8 14h-4L8 3z"/><path d="m8 3-7 14h4l7-14"/><path d="M5 17h15l-2 4H3z"/>',
            microsoft: '<rect x="3" y="3" width="8" height="8"/><rect x="13" y="3" width="8" height="8"/><rect x="3" y="13" width="8" height="8"/><rect x="13" y="13" width="8" height="8"/>',
            shield: '<path d="M12 3 20 6v5c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V6z"/><path d="m8.5 12 2.3 2.3 4.8-5"/>',
            download: '<path d="M12 3v12m-4-4 4 4 4-4"/><path d="M4 17v3h16v-3"/>',
            refresh: '<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.5 9A7 7 0 0 1 18 6l2 6M4 12l2 6a7 7 0 0 0 12.5-3"/>',
            link: '<path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1 0l-2 2A5 5 0 0 0 12 20.1l1.1-1.1"/>',
            folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 9h18"/>',
            database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
        };
        const allowedSizes = ["nav", "button", "small", "provider"];
        const iconSize = allowedSizes.includes(size) ? size : "button";
        return `<svg class="backup-icon-svg backup-icon-svg--${iconSize}" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.dashboard}</svg>`;
    }

    providerLogo(provider) {
        const logos = {
            "google-drive": `<svg class="provider-logo provider-logo-drive" viewBox="0 0 48 48" aria-hidden="true" focusable="false"><path fill="#00832D" d="M16.2 5.5h8.1l17.4 30.1h-8.1z"/><path fill="#0066DA" d="M7.4 30.5h33.8l-4.5 7.8H2.9z"/><path fill="#FFBA00" d="M16.2 5.5 1.4 30.5l4.5 7.8L24.3 5.5z"/></svg>`,
            onedrive: `<svg class="provider-logo provider-logo-onedrive" viewBox="0 0 48 48" aria-hidden="true" focusable="false"><path fill="#0078D4" d="M19.4 9.1c6.8-2.8 14.6.8 16.9 7.7 5.3-.2 9.7 3.7 9.7 8.7 0 5.2-4.2 8.7-9.6 8.7H11.8C5.6 34.2 2 30.7 2 25.8c0-5 4.2-8.8 9.3-8.8 1.4-3.6 4.2-6.3 8.1-7.9z"/><path fill="#1490DF" d="M10.2 22.1c3.5-5.7 10.8-7.5 16.5-4.1 2.5 1.5 4.2 3.7 5.1 6.2 4.4-1.2 8.6 1.2 9.7 4.7.7 2.2-.2 4.6-2.1 6.1H12c-4.8 0-7.2-2.6-7.2-5.9 0-3.2 2.2-5.8 5.4-7z"/></svg>`,
            gmail: `<svg class="provider-logo provider-logo-gmail" viewBox="0 0 48 48" aria-hidden="true" focusable="false"><path d="M7 37V12.5c0-2 2.3-3.1 3.9-1.9L24 21l13.1-10.4c1.6-1.2 3.9-.1 3.9 1.9V37" fill="none" stroke="#EA4335" stroke-width="5.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 18v19" stroke="#4285F4" stroke-width="5.2" stroke-linecap="round"/><path d="M41 18v19" stroke="#34A853" stroke-width="5.2" stroke-linecap="round"/><path d="M7 13l17 13" stroke="#FBBC04" stroke-width="3" stroke-linecap="round"/></svg>`,
            microsoft: `<svg class="provider-logo provider-logo-microsoft" viewBox="0 0 48 48" aria-hidden="true" focusable="false"><rect x="3" y="3" width="19" height="19" fill="#F25022"/><rect x="26" y="3" width="19" height="19" fill="#7FBA00"/><rect x="3" y="26" width="19" height="19" fill="#00A4EF"/><rect x="26" y="26" width="19" height="19" fill="#FFB900"/></svg>`,
            yahoo: `<span class="provider-wordmark provider-wordmark-yahoo" aria-hidden="true">yahoo<span>!</span></span>`,
        };
        return `<span class="provider-mark provider-mark--${provider}" aria-hidden="true">${logos[provider] || this.icon("cloud", "provider")}</span>`;
    }

    renderShell() {
        this.body.html(`
          <div class="hded-backup-manager" dir="rtl">
            <div class="backup-alert" id="backup-alert" style="display:none"></div>
            <nav class="backup-tabs" role="tablist" aria-label="أقسام مدير النسخ الاحتياطي">
              <button type="button" class="backup-tab-button tab-dashboard active" role="tab" aria-selected="true" aria-controls="backup-panel-dashboard" data-tab="dashboard">${this.icon("dashboard", "nav")}<span>لوحة التحكم</span></button>
              <button type="button" class="backup-tab-button tab-settings" role="tab" aria-selected="false" aria-controls="backup-panel-settings" data-tab="settings">${this.icon("settings", "nav")}<span>إعدادات النسخ</span></button>
              <button type="button" class="backup-tab-button tab-apps" role="tab" aria-selected="false" aria-controls="backup-panel-apps" data-tab="apps">${this.icon("apps", "nav")}<span>التطبيقات</span></button>
              <button type="button" class="backup-tab-button tab-external" role="tab" aria-selected="false" aria-controls="backup-panel-external" data-tab="external">${this.icon("cloud", "nav")}<span>التخزين والربط الخارجي</span></button>
            </nav>

            <div id="backup-panel-dashboard" class="backup-tab-panel active" data-panel="dashboard" role="tabpanel">
              <div class="backup-cards">
                <div class="backup-card"><div class="muted">عدد النسخ</div><div class="number" id="backup-count">—</div></div>
                <div class="backup-card"><div class="muted">النسخ المكتملة</div><div class="number" id="backup-complete">—</div></div>
                <div class="backup-card"><div class="muted">المساحة المستخدمة</div><div class="number" id="backup-size">—</div></div>
                <div class="backup-card"><div class="muted">أحدث نسخة</div><div class="latest" id="backup-latest">—</div></div>
              </div>
              <section class="backup-panel">
                <div class="panel-heading"><h3>حالة النسخ التلقائي</h3><span id="timer-state" class="state-pill">جارٍ التحميل</span></div>
                <div class="muted" id="schedule-info">—</div><div class="muted" id="backup-directory"></div>
              </section>
              <section class="backup-panel">
                <div class="panel-heading"><h3>النسخ الاحتياطية المحفوظة</h3><span class="muted">آخر 100 نسخة</span></div>
                <div class="table-responsive"><table class="table table-bordered backup-table">
                  <thead><tr><th>تاريخ النسخة</th><th>الحالة</th><th>الحجم</th><th>الملفات</th><th>الإجراءات</th></tr></thead>
                  <tbody id="backup-rows"><tr><td colspan="5" class="text-center">جارٍ تحميل النسخ...</td></tr></tbody>
                </table></div>
              </section>
            </div>

            <div id="backup-panel-settings" class="backup-tab-panel" data-panel="settings" role="tabpanel" hidden>
              <section class="backup-panel local-storage-panel">
                <div class="panel-heading"><h3>مكان حفظ النسخ الاحتياطية</h3><span class="muted">التخزين المحلي</span></div>
                <p class="muted">اكتب المسار الكامل لمجلد على خادم Ubuntu. اتركه فارغاً لاستخدام مجلد الموقع الافتراضي. يمكن اختيار مجلد على قرص داخلي أو قرص خارجي موصول بالخادم.</p>
                <div class="local-storage-fields">
                  <div><label for="backup-local-path">مسار مجلد النسخ</label><div class="backup-path-row"><input type="text" id="backup-local-path" class="form-control" dir="ltr" placeholder="/mnt/backup/hded"><button type="button" class="btn btn-default" id="backup-path-browse">${this.icon("folder")} استعراض الأقراص والمجلدات</button></div></div>
                  <label class="switch-label"><input type="checkbox" id="backup-require-mount"> اشترط أن يكون المجلد على قرص/وحدة تخزين منفصلة موصولة</label>
                </div>
                <div class="local-storage-actions"><button type="button" class="btn btn-default" id="backup-path-test">${this.icon("shield")} فحص المسار وإمكانية الكتابة</button><button type="button" class="btn btn-primary" id="backup-storage-save">حفظ مسار التخزين فقط</button><span id="backup-path-status" class="muted" aria-live="polite"></span></div>
                <p class="muted">هذا مسار على خادم Ubuntu وليس على جهاز المتصفح. الفحص ينشئ المجلد عند الحاجة ويتأكد من صلاحيات الحماية والمساحة المتاحة. عند تغيير المسار لا تُنقل النسخ القديمة أو تُحذف؛ يحتفظ التطبيق بسجل لمسارات التخزين السابقة ويعرض نسخها كمجلد سابق.</p>
              </section>
              <section class="backup-panel backup-mode-panel">
                <div class="panel-heading"><h3>نمط الحفظ</h3><span class="muted">اختر طريقة تكرار النسخ</span></div>
                <label for="backup-mode">طريقة إنشاء النسخ الاحتياطية</label>
                <select id="backup-mode" class="form-control">
                  <option value="scheduled">نسخ دوري تلقائي إلى نفس المجلد</option>
                  <option value="one_time">نسخة واحدة فقط — يدويًا دون تكرار تلقائي</option>
                </select>
                <p class="muted" id="backup-mode-note">سيتم إنشاء النسخ تلقائيًا حسب المواعيد المحددة أدناه، مع حفظها في مجلد التخزين المختار.</p>
              </section>
              <section class="backup-panel" id="schedule-controls">
                <div class="panel-heading"><h3>مواعيد النسخ الدوري</h3></div>
                <p class="muted">يمكن تفعيل أكثر من موعد. عند اختيار «نسخة واحدة فقط» يتم إيقاف هذه المواعيد، وتُنشأ نسخة واحدة عند الضغط على زر «إنشاء نسخة الآن».</p>
                <div class="schedule-grid">
                  <div class="schedule-option"><label class="switch-label"><input type="checkbox" id="daily-enabled"> نسخ يومي</label><label for="daily-time">الساعة</label><input type="time" id="daily-time" class="form-control" value="02:00"></div>
                  <div class="schedule-option"><label class="switch-label"><input type="checkbox" id="weekly-enabled"> نسخ أسبوعي</label><label for="weekly-day">يوم التنفيذ</label><select id="weekly-day" class="form-control"><option value="Mon">الاثنين</option><option value="Tue">الثلاثاء</option><option value="Wed">الأربعاء</option><option value="Thu">الخميس</option><option value="Fri">الجمعة</option><option value="Sat">السبت</option><option value="Sun">الأحد</option></select><label for="weekly-time">الساعة</label><input type="time" id="weekly-time" class="form-control" value="02:00"></div>
                  <div class="schedule-option"><label class="switch-label"><input type="checkbox" id="monthly-enabled"> نسخ شهري</label><label for="monthly-day">يوم الشهر</label><select id="monthly-day" class="form-control">${Array.from({length: 28}, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("")}</select><label for="monthly-time">الساعة</label><input type="time" id="monthly-time" class="form-control" value="02:00"></div>
                </div>
              </section>
              <section class="backup-panel">
                <div class="panel-heading"><h3>سياسة الاحتفاظ بالنسخ</h3><label class="switch-label"><input type="checkbox" id="retention-auto"> تطبيق الحذف التلقائي بعد نجاح النسخة</label></div>
                <p class="muted">يحتفظ النظام بأحدث نسخة من كل يوم/أسبوع/شهر ضمن العدد المحدد. النسخ غير المكتملة لا تُحذف تلقائياً.</p>
                <div class="retention-grid">
                  <div><label for="retention-daily">عدد النسخ اليومية</label><input type="number" min="1" max="365" id="retention-daily" class="form-control" value="7"></div>
                  <div><label for="retention-weekly">عدد النسخ الأسبوعية</label><input type="number" min="1" max="365" id="retention-weekly" class="form-control" value="4"></div>
                  <div><label for="retention-monthly">عدد النسخ الشهرية</label><input type="number" min="1" max="365" id="retention-monthly" class="form-control" value="12"></div>
                </div>
                <div class="retention-actions"><button type="button" class="btn btn-warning" id="preview-retention">${this.icon("shield")} معاينة النسخ التي ستُحذف</button><button type="button" class="btn btn-danger" id="apply-retention">حذف النسخ الزائدة الآن</button></div>
                <div id="retention-preview" class="retention-preview" style="display:none"></div>
              </section>
              <div class="settings-actions"><button type="button" class="btn btn-primary" id="save-settings">حفظ جميع الإعدادات</button></div>
            </div>

            <div id="backup-panel-apps" class="backup-tab-panel" data-panel="apps" role="tabpanel" hidden>
              <section class="backup-panel">
                <div class="panel-heading"><h3>أرشفة مصادر التطبيقات</h3><label class="switch-label"><input type="checkbox" id="apps-archive-enabled"> تضمين مصادر التطبيقات في النسخ</label></div>
                <label class="switch-label app-auto-label"><input type="checkbox" id="apps-auto-include"> إضافة التطبيقات الجديدة تلقائياً إلى النسخ</label>
                <p class="muted">عند تفعيل الاكتشاف التلقائي، يضيف النظام التطبيقات الموجودة في مجلد apps والتي تحتوي على hooks.py، بما فيها التطبيقات التي تنشئها لاحقاً. تطبيقا frappe وerpnext غير محددين افتراضياً لتقليل حجم الأرشيف؛ يمكنك تحديدهما هنا. تُستبعد المجلدات المؤقتة وبيئات Python ومجلدات Git وبعض الملفات السرية الشائعة.</p>
                <div class="panel-heading app-list-heading"><h3>التطبيقات المكتشفة</h3><span class="muted" id="app-count">—</span></div>
                <div id="apps-list" class="apps-list"><p class="muted">جارٍ اكتشاف التطبيقات...</p></div>
              </section>
              <div class="settings-actions"><button type="button" class="btn btn-primary" id="save-settings-apps">حفظ إعدادات التطبيقات</button></div>
            </div>

            <div id="backup-panel-external" class="backup-tab-panel" data-panel="external" role="tabpanel" hidden>
              <section class="backup-panel">
                <div class="panel-heading"><h3>التخزين السحابي للنسخ الكاملة</h3><span class="state-pill is-off">الربط الفعلي غير مفعّل</span></div>
                <p class="muted">تستخدم هذه الخدمات لحفظ ملفات النسخ خارج جهاز ERPNext. أزرار الإعداد تعرض خطوات التجهيز؛ لن تظهر الخدمة متصلة قبل تنفيذ OAuth ونجاح رفع ملف تجريبي والتحقق منه.</p>
                <div class="provider-grid">
                  <article class="provider-card provider-drive">
                    <div class="provider-title">${this.providerLogo("google-drive")}<div><h4>Google Drive</h4><p>تخزين قاعدة البيانات والملفات وأرشيف التطبيقات خارج الجهاز.</p></div></div>
                    <span class="state-pill is-off">غير مربوط</span>
                    <button type="button" class="btn provider-action provider-drive-button cloud-setup-button" data-cloud-provider="google">${this.icon("drive")} إعداد ربط Google Drive</button>
                  </article>
                  <article class="provider-card provider-onedrive">
                    <div class="provider-title">${this.providerLogo("onedrive")}<div><h4>Microsoft OneDrive</h4><p>يدعم حسابات Microsoft الشخصية مثل Hotmail وOutlook.</p></div></div>
                    <span class="state-pill is-off">غير مربوط</span>
                    <button type="button" class="btn provider-action provider-onedrive-button cloud-setup-button" data-cloud-provider="microsoft">${this.icon("cloud")} إعداد ربط OneDrive</button>
                  </article>
                </div>
              </section>

              <section class="backup-panel">
                <div class="panel-heading"><h3>ربط حسابات البريد للتنبيهات</h3><span class="muted">لكل مزود زر ربط مستقل</span></div>
                <p class="muted">يتم إعداد حساب الإرسال من خلال نموذج Email Account الأصلي في ERPNext. لا تضع كلمة مرور بريدك في هذه الصفحة؛ استخدم كلمة مرور تطبيق أو OAuth حسب متطلبات مزود البريد.</p>
                <div class="provider-grid mail-provider-grid">
                  <article class="provider-card provider-gmail">
                    <div class="provider-title">${this.providerLogo("gmail")}<div><h4>Gmail / Google Workspace</h4><p class="provider-account-status" data-email-status="gmail">جارٍ قراءة حالة الحساب</p></div></div>
                    <div class="provider-meta"><span>SMTP: smtp.gmail.com</span><span>587 STARTTLS أو 465 SSL</span></div>
                    <button type="button" class="btn provider-action provider-gmail-button email-connect-button" data-email-provider="gmail">${this.icon("mail")} ربط Gmail</button>
                  </article>
                  <article class="provider-card provider-outlook">
                    <div class="provider-title">${this.providerLogo("microsoft")}<div><h4>Outlook / Hotmail</h4><p class="provider-account-status" data-email-status="outlook">جارٍ قراءة حالة الحساب</p></div></div>
                    <div class="provider-meta"><span>SMTP: smtp-mail.outlook.com</span><span>587 STARTTLS — OAuth2 / Modern Auth</span></div>
                    <button type="button" class="btn provider-action provider-outlook-button email-connect-button" data-email-provider="outlook">${this.icon("mail")} ربط Outlook / Hotmail</button>
                  </article>
                  <article class="provider-card provider-yahoo">
                    <div class="provider-title">${this.providerLogo("yahoo")}<div><h4>Yahoo Mail</h4><p class="provider-account-status" data-email-status="yahoo">جارٍ قراءة حالة الحساب</p></div></div>
                    <div class="provider-meta"><span>SMTP: smtp.mail.yahoo.com</span><span>465 SSL أو 587 STARTTLS</span></div>
                    <button type="button" class="btn provider-action provider-yahoo-button email-connect-button" data-email-provider="yahoo">${this.icon("mail")} ربط Yahoo Mail</button>
                  </article>
                </div>
              </section>
              <div class="backup-note">مهم: إنشاء حساب بريد في ERPNext لا يعني ربط التخزين السحابي. Google Drive وOneDrive يحتاجان تفويض OAuth مستقل. Yahoo Mail مخصص للتنبيهات البريدية وليس لتخزين ملفات النسخ الكبيرة كمرفقات.</div>
            </div>
            <p class="backup-note">ملف إعدادات الموقع الحساس لا يتاح للتنزيل من المتصفح. الاستعادة ستضاف بعد وضع آلية استعادة واختبارها.</p>
          </div>
        `);

        // Bind each tab directly to its button. This avoids relying on delegated events
        // attached to the Desk page body, which can differ between Frappe page layouts.
        this.body.find(".backup-tab-button").off("click.hdedBackupTabs").on("click.hdedBackupTabs", (event) => {
            event.preventDefault();
            event.stopPropagation();
            this.showTab($(event.currentTarget).attr("data-tab"));
        });
        this.showTab("dashboard");

        this.body.find("#save-settings, #save-settings-apps").on("click", () => this.saveSettings());
        this.body.find("#backup-path-test").on("click", () => this.testBackupPath());
        this.body.find("#backup-path-browse").on("click", () => this.openStorageBrowser());
        this.body.find("#backup-mode").on("change", () => {
            this.updateBackupModeUI(this.body.find("#backup-mode").val(), this.currentBackupSettings || {});
            this.refreshPrimaryAction();
        });
        this.body.find("#backup-local-path").on("input change", () => this.refreshPrimaryAction());
        this.body.find("#backup-require-mount").on("change", () => this.refreshPrimaryAction());
        this.body.find("#backup-storage-save").on("click", () => this.saveStorageSettings());
        this.body.find("#preview-retention").on("click", () => this.previewRetention());
        this.body.find("#apply-retention").on("click", () => this.applyRetention());
        this.body.find(".email-connect-button").on("click", (event) => this.openEmailConnection($(event.currentTarget).attr("data-email-provider")));
        this.body.find(".cloud-setup-button").on("click", (event) => this.openCloudSetup($(event.currentTarget).attr("data-cloud-provider")));
        this.body.on("click", ".verify-backup", (event) => this.verify($(event.currentTarget).data("timestamp"), $(event.currentTarget).data("storage") || "active"));
        this.body.on("click", ".download-backup", (event) => this.download($(event.currentTarget).data("filename"), $(event.currentTarget).data("storage") || "active"));
    }

    showTab(name) {
        const allowed = ["dashboard", "settings", "apps", "external"];
        if (!allowed.includes(name)) return;

        this.body.find(".backup-tab-button").each((_, element) => {
            const button = $(element);
            const active = button.attr("data-tab") === name;
            button.toggleClass("active", active).attr("aria-selected", active ? "true" : "false");
        });
        this.body.find(".backup-tab-panel").each((_, element) => {
            const panel = $(element);
            const active = panel.attr("data-panel") === name;
            panel.toggleClass("active", active).prop("hidden", !active).attr("aria-hidden", active ? "false" : "true");
        });
    }

    call(method, args = {}) {
        return new Promise((resolve, reject) => frappe.call({
            method: `hded_backup_manager.api.${method}`, args,
            callback: (r) => resolve(r.message), error: (e) => reject(e),
        }));
    }

    async load() {
        this.showAlert("جارٍ تحديث معلومات النسخ الاحتياطي...", "info");
        try {
            const data = await this.call("get_dashboard");
            this.renderData(data);
            this.hideAlert();
        } catch (error) {
            this.showAlert("تعذر قراءة معلومات النسخ الاحتياطي. تحقق من صلاحيات مدير النظام وسجل Frappe.", "danger");
        }
    }

    renderData(data) {
        const summary = data.summary || {}, status = data.status || {}, settings = data.settings || {};
        this.currentBackupSettings = settings;
        const schedule = settings.schedule || {}, retention = settings.retention || {}, apps = settings.apps || {};
        this.body.find("#backup-count").text(summary.backup_count ?? 0);
        this.body.find("#backup-complete").text(summary.complete_count ?? 0);
        this.body.find("#backup-size").text(summary.total_size || "0 B");
        this.body.find("#backup-latest").text(summary.latest || "لا توجد نسخ بعد");
        const storageWarning = summary.storage_error ? ` — تنبيه: ${summary.storage_error}` : "";
        const diskLabel = summary.storage_error ? "القرص غير متاح" : summary.is_separate_mount ? "وحدة تخزين منفصلة" : "القرص المحلي";
        this.body.find("#backup-directory").text(`مجلد التخزين الحالي: ${summary.directory || "غير متاح"} — ${diskLabel} — المساحة المتاحة: ${summary.free_space || "غير متاحة"}${storageWarning}`).toggleClass("text-danger", !!summary.storage_error);
        this.body.find("#backup-local-path").val((settings.storage || {}).local_path || "");
        this.body.find("#backup-require-mount").prop("checked", !!(settings.storage || {}).require_mount);
        this.body.find("#timer-state").text(status.timer_active ? "الجدولة مفعّلة" : "الجدولة متوقفة").toggleClass("is-on", !!status.timer_active).toggleClass("is-off", !status.timer_active);
        this.body.find("#schedule-info").text(`موعد التنفيذ القادم: ${status.next_run || "غير متاح"} — آخر نتيجة للخدمة: ${status.service_result || "غير متاح"}`);

        this.body.find("#backup-mode").val(settings.backup_mode || "scheduled");
        this.updateBackupModeUI(settings.backup_mode || "scheduled", settings);
        this.refreshPrimaryAction();
        this.body.find("#daily-enabled").prop("checked", !!(schedule.daily || {}).enabled);
        this.body.find("#daily-time").val((schedule.daily || {}).time || "02:00");
        this.body.find("#weekly-enabled").prop("checked", !!(schedule.weekly || {}).enabled);
        this.body.find("#weekly-day").val((schedule.weekly || {}).weekday || "Sun");
        this.body.find("#weekly-time").val((schedule.weekly || {}).time || "02:00");
        this.body.find("#monthly-enabled").prop("checked", !!(schedule.monthly || {}).enabled);
        this.body.find("#monthly-day").val(String((schedule.monthly || {}).day || 1));
        this.body.find("#monthly-time").val((schedule.monthly || {}).time || "02:00");
        this.body.find("#retention-auto").prop("checked", !!retention.auto_apply);
        this.body.find("#retention-daily").val(retention.daily ?? 7);
        this.body.find("#retention-weekly").val(retention.weekly ?? 4);
        this.body.find("#retention-monthly").val(retention.monthly ?? 12);
        this.body.find("#apps-archive-enabled").prop("checked", apps.archive_enabled !== false);
        this.body.find("#apps-auto-include").prop("checked", apps.auto_include_new_apps !== false);
        this.renderApps(data.apps || []);
        this.renderEmailConnections(data.email_connections || {});

        const rows = (data.backups || []).map((item) => {
            const state = item.complete ? '<span class="state-pill is-on">مكتملة</span>' : '<span class="state-pill is-off">غير مكتملة</span>';
            const labels = { database: "قاعدة البيانات", public: "الملفات العامة", private: "الملفات الخاصة", apps: "مصادر التطبيقات" };
            const storage = item.storage || "active";
            const storageLabel = storage === "active" ? '<div class="muted">المجلد المحدد حالياً</div>' : '<div class="muted">مجلد سابق</div>';
            const links = Object.entries(item.files || {}).map(([kind, filename]) => `<button type="button" class="btn btn-xs download-backup download-${kind}" data-filename="${frappe.utils.escape_html(filename)}" data-storage="${storage}">${this.icon("download", "small")} ${labels[kind] || kind}</button>`).join(" ");
            const appState = item.apps_available ? '<span class="muted">أرشيف التطبيقات محفوظ</span>' : '<span class="muted">لا يوجد أرشيف تطبيقات</span>';
            return `<tr><td>${frappe.utils.escape_html(item.created)}</td><td>${state} <span class="muted">(${item.file_count}/${item.file_total})</span><div>${appState}</div>${storageLabel}</td><td>${frappe.utils.escape_html(item.size_label)}</td><td>${links}</td><td><button type="button" class="btn btn-xs verify-backup" data-timestamp="${frappe.utils.escape_html(item.timestamp)}" data-storage="${storage}" ${item.complete ? "" : "disabled"}>${this.icon("shield", "small")} فحص السلامة</button></td></tr>`;
        }).join("");
        this.body.find("#backup-rows").html(rows || '<tr><td colspan="5" class="text-center muted">لا توجد نسخ احتياطية لهذا الموقع</td></tr>');
    }

    renderApps(apps) {
        this.body.find("#app-count").text(`${apps.length} تطبيق`);
        const html = apps.map((app) => `<label class="app-choice"><input type="checkbox" class="app-include" value="${frappe.utils.escape_html(app.name)}" ${app.selected ? "checked" : ""} ${app.name === "hded_backup_manager" ? "disabled" : ""}><span class="app-name">${frappe.utils.escape_html(app.name)}</span><span class="muted">${app.installed ? "مضاف إلى Bench" : "مجلد موجود"}</span></label>`).join("");
        this.body.find("#apps-list").html(html || '<p class="muted">لم يتم اكتشاف تطبيقات قابلة للأرشفة.</p>');
    }

    renderEmailConnections(connections) {
        const labels = { gmail: "Gmail", outlook: "Outlook / Hotmail", yahoo: "Yahoo Mail" };
        Object.entries(labels).forEach(([key, label]) => {
            const account = connections[key];
            const target = this.body.find(`[data-email-status="${key}"]`);
            if (account && account.email_id) {
                target.text(`حساب إرسال مسجّل: ${account.email_id}`).removeClass("not-configured").addClass("configured");
            } else {
                target.text("لم يتم إعداد حساب إرسال بعد").removeClass("configured").addClass("not-configured");
            }
        });
    }

    openEmailConnection(providerKey) {
        const providers = {
            gmail: {
                title: "ربط Gmail / Google Workspace",
                service: "GMail",
                details: ["في نموذج Email Account اختر خدمة GMail.", "لإرسال البريد: smtp.gmail.com — المنفذ 587 مع STARTTLS، أو 465 مع SSL/TLS.", "لحساب Gmail الشخصي، فعّل التحقق بخطوتين وأنشئ App Password واستخدمها بدلاً من كلمة مرور الحساب المعتادة."],
                note: "يُنشأ الحساب داخل ERPNext ولا تُحفظ كلمة المرور في إعدادات مدير النسخ الاحتياطي.",
            },
            outlook: {
                title: "ربط Outlook / Hotmail",
                service: "Outlook.com",
                details: ["في نموذج Email Account اختر Outlook.com.", "خادم SMTP: smtp-mail.outlook.com — المنفذ 587 — STARTTLS.", "تتطلب حسابات Outlook.com مصادقة حديثة OAuth2 / Modern Auth؛ اتبع خيار المصادقة الذي يعرضه نموذج ERPNext ولا تستخدم كلمة مرور حسابك في صفحة مدير النسخ."],
                note: "يدعم هذا الخيار عناوين Hotmail وOutlook المرتبطة بحساب Microsoft الشخصي.",
            },
            yahoo: {
                title: "ربط Yahoo Mail",
                service: "Yahoo Mail",
                details: ["في نموذج Email Account اختر خدمة Yahoo Mail.", "خادم SMTP: smtp.mail.yahoo.com — المنفذ 465 أو 587، مع تشفير SSL/TLS حسب إعداد المنفذ.", "أنشئ كلمة مرور تطبيق (App Password) من إعدادات أمان Yahoo، واستخدمها في نموذج حساب البريد."],
                note: "سيستخدم الحساب لإرسال إشعارات النسخ؛ لا نرسل ملفات النسخ الكبيرة كمرفقات بريدية.",
            },
        };
        const provider = providers[providerKey];
        if (!provider) return;
        const details = provider.details.map((line) => `<li>${frappe.utils.escape_html(line)}</li>`).join("");
        const dialog = new frappe.ui.Dialog({
            title: provider.title,
            fields: [{ fieldtype: "HTML", fieldname: "provider_details" }],
            primary_action_label: "فتح نموذج ربط البريد في ERPNext",
            primary_action: () => {
                dialog.hide();
                frappe.new_doc("Email Account", { service: provider.service });
            },
        });
        dialog.fields_dict.provider_details.$wrapper.html(`<div class="mail-setup-dialog"><ol>${details}</ol><p>${frappe.utils.escape_html(provider.note)}</p><p class="muted">بعد حفظ الحساب بنجاح، ارجع إلى هذه الصفحة واضغط تحديث لمعرفة حالة الإعداد.</p></div>`);
        dialog.show();
    }

    openCloudSetup(providerKey) {
        const providers = {
            google: {
                title: "إعداد التخزين في Google Drive",
                console: "https://console.cloud.google.com/apis/credentials",
                consoleLabel: "فتح Google Cloud Console",
                details: ["إنشاء مشروع في Google Cloud وتفعيل Google Drive API.", "إعداد OAuth consent screen وإنشاء OAuth Client ID لنوع Web application.", "إضافة عنوان الإرجاع (Redirect URI) الذي سيحدده إصدار OAuth المخصص لـ HDED.", "تخزين Client ID وClient Secret في إعدادات خادمية محمية، ثم اختبار رفع نسخة واستئنافها والتحقق من بصمتها."],
                warning: "لا يمكن إتمام الربط الفعلي من هذا الزر حتى يُجهّز مسار OAuth الآمن في التطبيق. لا تدخل كلمة مرور Google هنا.",
            },
            microsoft: {
                title: "إعداد التخزين في Microsoft OneDrive",
                console: "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
                consoleLabel: "فتح Microsoft Entra App Registrations",
                details: ["تسجيل تطبيق في Microsoft Entra لدعم الحسابات الشخصية.", "إضافة صلاحيات Microsoft Graph الضرورية لرفع ملفات OneDrive.", "إعداد Redirect URI وتوليد Client Secret.", "تخزين بيانات OAuth في الخادم، ثم اختبار رفع نسخة واستئنافها والتحقق من بصمتها."],
                warning: "زر الإعداد يفتح بوابة تسجيل التطبيق فقط؛ الربط الفعلي لا يُعد مكتملاً حتى إضافة تدفق OAuth واختبار رفع حقيقي.",
            },
        };
        const provider = providers[providerKey];
        if (!provider) return;
        const list = provider.details.map((line) => `<li>${frappe.utils.escape_html(line)}</li>`).join("");
        const dialog = new frappe.ui.Dialog({
            title: provider.title,
            fields: [{ fieldtype: "HTML", fieldname: "cloud_details" }],
            primary_action_label: provider.consoleLabel,
            primary_action: () => {
                window.open(provider.console, "_blank", "noopener,noreferrer");
            },
        });
        dialog.fields_dict.cloud_details.$wrapper.html(`<div class="cloud-setup-dialog"><ol>${list}</ol><div class="alert alert-warning">${frappe.utils.escape_html(provider.warning)}</div></div>`);
        dialog.show();
    }

    refreshPrimaryAction() {
        const saved = this.currentBackupSettings || {};
        const selectedMode = this.body.find("#backup-mode").val() || "scheduled";
        const selectedPath = (this.body.find("#backup-local-path").val() || "").trim();
        const savedPath = ((saved.storage || {}).local_path || "").trim();
        const selectedMount = this.body.find("#backup-require-mount").is(":checked");
        const savedMount = !!((saved.storage || {}).require_mount);
        const unsaved = selectedMode !== (saved.backup_mode || "scheduled")
            || selectedPath !== savedPath
            || selectedMount !== savedMount;
        if (unsaved) {
            this.page.set_primary_action("احفظ الإعدادات أولاً", () => frappe.msgprint("احفظ نمط النسخ ومسار التخزين أولاً قبل بدء النسخ، حتى لا تُنشأ النسخة في وجهة أو بنمط غير المقصود."), "save");
        } else if (selectedMode === "one_time" && saved.one_time_completed_at) {
            this.page.set_primary_action("اكتملت النسخة الواحدة", () => frappe.msgprint("تم تنفيذ النسخة المحددة لمرة واحدة بالفعل. لن يبدأ النظام نسخة أخرى حتى تغيّر نمط الحفظ وتحفظ الإعدادات من جديد."), "check");
        } else {
            this.page.set_primary_action("إنشاء نسخة الآن", () => this.startBackup(), "database");
        }
    }

    updateBackupModeUI(mode, settings = {}) {
        const oneTime = mode === "one_time";
        this.body.find("#schedule-controls :input").prop("disabled", oneTime);
        this.body.find("#schedule-controls").toggleClass("backup-schedule-disabled", oneTime);
        let note = "سيتم إنشاء النسخ تلقائيًا حسب المواعيد المحددة أدناه، مع حفظها في مجلد التخزين المختار.";
        if (oneTime && settings.one_time_completed_at) {
            note = `اكتملت النسخة الواحدة بتاريخ ${settings.one_time_completed_at}. تم منع أي تشغيل جديد لهذا النمط.`;
        } else if (oneTime) {
            note = "لن يعمل النسخ تلقائيًا ولن يتكرر. بعد حفظ الإعدادات، اضغط «إنشاء نسخة الآن» لإنشاء نسخة واحدة فقط. بعد نجاحها سيمنع النظام تكرارها بهذا النمط.";
        }
        this.body.find("#backup-mode-note").text(note);
    }

    async openStorageBrowser() {
        const dialog = new frappe.ui.Dialog({
            title: "استعراض أقراص ومجلدات خادم Ubuntu",
            fields: [{ fieldtype: "HTML", fieldname: "storage_browser" }],
            primary_action_label: "إغلاق",
            primary_action: () => dialog.hide(),
        });
        dialog.show();
        const container = dialog.fields_dict.storage_browser.$wrapper;
        container.html('<div class="storage-browser-loading">جارٍ اكتشاف الأقراص ووحدات التخزين المركّبة...</div>');

        container.off("click.hdedStorageBrowser")
            .on("click.hdedStorageBrowser", ".storage-volume-open", async (event) => {
                const button = $(event.currentTarget);
                await this.browseStorageFolder(dialog, container, button.attr("data-mount"), button.attr("data-path"));
            })
            .on("click.hdedStorageBrowser", ".storage-folder-open", async (event) => {
                const button = $(event.currentTarget);
                await this.browseStorageFolder(dialog, container, button.attr("data-mount"), button.attr("data-path"));
            })
            .on("click.hdedStorageBrowser", ".storage-folder-up", async (event) => {
                const button = $(event.currentTarget);
                await this.browseStorageFolder(dialog, container, button.attr("data-mount"), button.attr("data-path"));
            })
            .on("click.hdedStorageBrowser", ".storage-back-volumes", () => this.loadStorageVolumes(dialog, container))
            .on("click.hdedStorageBrowser", ".storage-folder-choose", (event) => {
                const button = $(event.currentTarget);
                const path = button.attr("data-path");
                const mountPath = button.attr("data-mount");
                this.body.find("#backup-local-path").val(path);
                this.body.find("#backup-require-mount").prop("checked", mountPath !== "/");
                this.refreshPrimaryAction();
                this.body.find("#backup-path-status").text("تم اختيار المجلد. نفّذ الفحص ثم احفظ المسار.").removeClass("text-danger").addClass("text-success");
                dialog.hide();
                this.showAlert(`تم اختيار مجلد التخزين: ${path}. افحص المسار ثم احفظه.`, "success");
            });

        await this.loadStorageVolumes(dialog, container);
    }

    async loadStorageVolumes(dialog, container) {
        container.html('<div class="storage-browser-loading">جارٍ قراءة الأقراص المركّبة...</div>');
        try {
            const result = await this.call("get_storage_locations");
            const locations = result.locations || [];
            if (!locations.length) {
                container.html('<div class="alert alert-warning">لم يتم العثور على أقراص محلية مركّبة يمكن استعراضها.</div>');
                return;
            }
            const cards = locations.map((item) => {
                const path = frappe.utils.escape_html(item.path);
                const label = frappe.utils.escape_html(item.label);
                const kind = frappe.utils.escape_html(item.kind_label);
                const size = frappe.utils.escape_html(item.size || "غير معروف");
                const free = this.formatBytes(item.free_bytes);
                return `<button type="button" class="storage-volume-open" data-mount="${path}" data-path="${path}">
                    <span class="storage-volume-icon">${this.icon("database", "small")}</span>
                    <span class="storage-volume-info"><strong>${label}</strong><small>${kind} · ${size} · المتاح ${free}</small><code>${path}</code></span>
                    <span class="storage-volume-arrow">فتح المجلدات ←</span>
                </button>`;
            }).join("");
            container.html(`<div class="storage-browser-intro">اختر القرص الذي تريد حفظ النسخ عليه. هذه الأقراص موجودة على خادم Ubuntu الذي يعمل عليه ERPNext، وليست أقراص جهاز Windows أو الهاتف.</div><div class="storage-volume-list">${cards}</div>`);
        } catch (error) {
            container.html('<div class="alert alert-danger">تعذر قراءة الأقراص. تحقق من صلاحيات نظام التشغيل وسجل Frappe.</div>');
        }
    }

    async browseStorageFolder(dialog, container, mountPath, path) {
        container.find(".storage-browser-loading, .storage-browser-error").remove();
        container.prepend('<div class="storage-browser-loading">جارٍ قراءة المجلد...</div>');
        try {
            const result = await this.call("browse_storage_directory", { mount_path: mountPath, path });
            const current = frappe.utils.escape_html(result.current_path);
            const mount = frappe.utils.escape_html(result.mount_path);
            const kind = frappe.utils.escape_html(result.mount_kind || "");
            const parent = result.parent_path ? `<button type="button" class="btn btn-default storage-folder-up" data-mount="${mount}" data-path="${frappe.utils.escape_html(result.parent_path)}">${this.icon("folder", "small")} رجوع إلى المجلد الأعلى</button>` : "";
            const folders = (result.directories || []).map((item) => {
                const name = frappe.utils.escape_html(item.name);
                const child = frappe.utils.escape_html(item.path);
                return `<button type="button" class="storage-folder-open" data-mount="${mount}" data-path="${child}">${this.icon("folder", "small")} <span>${name}</span><span class="storage-folder-open-label">فتح</span></button>`;
            }).join("");
            const choose = result.can_select
                ? `<button type="button" class="btn btn-primary storage-folder-choose" data-mount="${mount}" data-path="${current}">اختيار هذا المجلد للحفظ</button>`
                : '<span class="muted">اختر مجلدًا فرعيًا داخل القرص؛ لا يمكن حفظ النسخ في جذر القرص مباشرة.</span>';
            container.html(`<div class="storage-browser-toolbar"><button type="button" class="btn btn-default storage-back-volumes">${this.icon("database", "small")} الأقراص</button>${parent}<span class="storage-browser-kind">${kind}</span></div><div class="storage-browser-current"><small>المسار الحالي</small><code dir="ltr">${current}</code><small>المساحة المتاحة: ${this.formatBytes(result.free_bytes)}</small></div><div class="storage-folder-list">${folders || '<p class="muted">لا توجد مجلدات فرعية ظاهرة داخل هذا المجلد.</p>'}</div><div class="storage-browser-select">${choose}</div>`);
        } catch (error) {
            container.html('<div class="alert alert-danger storage-browser-error">تعذر استعراض هذا المجلد. قد تكون الوحدة مفصولة أو لا توجد صلاحية قراءة.</div><button type="button" class="btn btn-default storage-back-volumes">العودة إلى الأقراص</button>');
        }
    }

    formatBytes(bytes) {
        let value = Number(bytes || 0);
        if (!Number.isFinite(value) || value < 0) return "غير متاحة";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let index = 0;
        while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
        return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
    }

    async testBackupPath() {
        const path = (this.body.find("#backup-local-path").val() || "").trim();
        const require_mount = this.body.find("#backup-require-mount").is(":checked");
        const status = this.body.find("#backup-path-status");
        status.text("جارٍ فحص المسار...").removeClass("text-danger text-success");
        try {
            const result = await this.call("test_backup_path", { path, require_mount });
            status.text(`✓ ${result.message} — المساحة المتاحة: ${result.free_space} — نقطة التركيب: ${result.mount_target}`).addClass("text-success");
            this.showAlert("اجتاز مجلد التخزين الفحص ويمكن استخدامه للنسخ الاحتياطي.", "success");
        } catch (error) {
            status.text("فشل فحص المسار. راجع رسالة الخطأ.").addClass("text-danger");
            this.showAlert("تعذر اعتماد مجلد التخزين. تحقق من المسار والقرص والصلاحيات.", "danger");
        }
    }

    async saveStorageSettings() {
        const storage = {
            local_path: (this.body.find("#backup-local-path").val() || "").trim(),
            require_mount: this.body.find("#backup-require-mount").is(":checked"),
        };
        if (storage.require_mount && !storage.local_path) {
            frappe.msgprint("أدخل مسار مجلد القرص الخارجي أولاً.");
            return;
        }
        frappe.confirm(
            "سيتم فحص مسار التخزين وحفظه فقط. لن تتغير مواعيد النسخ أو حالة الجدولة أو سياسة الاحتفاظ أو إعدادات التطبيقات. هل تريد المتابعة؟",
            async () => {
                this.showAlert("جارٍ فحص مسار التخزين وحفظه...", "info");
                try {
                    const result = await this.call("save_storage_settings", { storage_json: JSON.stringify(storage) });
                    this.showAlert(result.message || "تم حفظ مسار التخزين", "success");
                    await this.load();
                } catch (error) {
                    this.showAlert("تعذر حفظ مسار التخزين. تحقق من المسار والقرص والصلاحيات.", "danger");
                }
            }
        );
    }

    collectSettings() {
        const selectedApps = this.body.find(".app-include:checked").map((_, el) => $(el).val()).get();
        return {
            storage: {
                local_path: (this.body.find("#backup-local-path").val() || "").trim(),
                require_mount: this.body.find("#backup-require-mount").is(":checked"),
            },
            backup_mode: this.body.find("#backup-mode").val() || "scheduled",
            schedule_enabled: (this.body.find("#backup-mode").val() || "scheduled") === "scheduled",
            schedule: {
                daily: { enabled: this.body.find("#daily-enabled").is(":checked"), time: this.body.find("#daily-time").val() || "02:00" },
                weekly: { enabled: this.body.find("#weekly-enabled").is(":checked"), weekday: this.body.find("#weekly-day").val(), time: this.body.find("#weekly-time").val() || "02:00" },
                monthly: { enabled: this.body.find("#monthly-enabled").is(":checked"), day: Number(this.body.find("#monthly-day").val() || 1), time: this.body.find("#monthly-time").val() || "02:00" },
            },
            retention: { auto_apply: this.body.find("#retention-auto").is(":checked"), daily: Number(this.body.find("#retention-daily").val()), weekly: Number(this.body.find("#retention-weekly").val()), monthly: Number(this.body.find("#retention-monthly").val()) },
            apps: { archive_enabled: this.body.find("#apps-archive-enabled").is(":checked"), auto_include_new_apps: this.body.find("#apps-auto-include").is(":checked"), selected_apps: selectedApps },
        };
    }

    async saveSettings() {
        const settings = this.collectSettings();
        if (settings.schedule_enabled && !Object.values(settings.schedule).some((row) => row.enabled)) { frappe.msgprint("فعّل نوعاً واحداً على الأقل من الجدولة، أو أوقف الجدولة التلقائية."); return; }
        if (Object.values(settings.retention).filter((value) => typeof value === "number").some((value) => !Number.isInteger(value) || value < 1 || value > 365)) { frappe.msgprint("قيم الاحتفاظ يجب أن تكون أعداداً صحيحة بين 1 و365."); return; }
        const settingsJson = JSON.stringify(settings);
        const confirmAndSave = (message) => frappe.confirm(message, async () => {
            this.showAlert("جارٍ حفظ الإعدادات...", "info");
            try { const result = await this.call("save_settings", { settings_json: settingsJson }); this.showAlert(result.message || "تم حفظ الإعدادات", "success"); await this.load(); }
            catch (error) { this.showAlert("تعذر حفظ الإعدادات. راجع رسالة الخطأ في سجل Frappe.", "danger"); }
        });
        if (settings.retention.auto_apply) {
            try {
                const plan = await this.call("preview_retention", { settings_json: settingsJson });
                confirmAndSave(`سيتم حفظ الإعدادات وتفعيل الحذف التلقائي بعد كل نسخة ناجحة. وفق البيانات الحالية، توجد ${plan.delete_count} مجموعة نسخ مكتملة مرشحة للحذف عند تطبيق السياسة. النسخ غير المكتملة لن تُحذف. هل تريد تفعيل ذلك؟`);
            } catch (error) { this.showAlert("تعذر معاينة سياسة الاحتفاظ. لم يتم حفظ الإعدادات.", "danger"); }
        } else {
            confirmAndSave("سيتم حفظ أوقات النسخ وسياسة الاحتفاظ وإعدادات أرشفة التطبيقات. الحذف التلقائي غير مفعّل. هل تريد المتابعة؟");
        }
    }

    async previewRetention() {
        this.showAlert("جارٍ حساب النسخ التي ستبقى والنسخ المرشحة للحذف...", "info");
        try {
            const plan = await this.call("preview_retention", { settings_json: JSON.stringify(this.collectSettings()) });
            const rows = (plan.delete || []).map((item) => `<tr><td>${frappe.utils.escape_html(item.created)}</td><td>${frappe.utils.escape_html(item.size_label)}</td></tr>`).join("");
            const html = `<div class="retention-result-summary">سيبقى ${plan.keep_count} مجموعة نسخ مكتملة، والمرشح للحذف ${plan.delete_count} مجموعة. النسخ غير المكتملة المحفوظة: ${plan.incomplete_preserved}.</div><div class="table-responsive"><table class="table table-bordered"><thead><tr><th>تاريخ النسخة المرشحة للحذف</th><th>الحجم</th></tr></thead><tbody>${rows || '<tr><td colspan="2">لا توجد مجموعات مرشحة للحذف.</td></tr>'}</tbody></table></div><p class="muted">هذه معاينة فقط؛ لم يُحذف أي ملف.</p>`;
            this.body.find("#retention-preview").html(html).show();
            this.showAlert("اكتملت معاينة سياسة الاحتفاظ. لم يتم حذف أي ملف.", "success");
        } catch (error) { this.showAlert("تعذر حساب سياسة الاحتفاظ.", "danger"); }
    }

    async applyRetention() {
        try {
            const settingsJson = JSON.stringify(this.collectSettings());
            const plan = await this.call("preview_retention", { settings_json: settingsJson });
            if (!plan.delete_count) { this.showAlert("لا توجد مجموعات نسخ مكتملة مرشحة للحذف.", "info"); return; }
            frappe.confirm(`المعاينة الحالية تحدد ${plan.delete_count} مجموعة نسخ مكتملة للحذف، مع الإبقاء على ${plan.keep_count} مجموعة. لن تُحذف النسخ غير المكتملة. هل تريد تنفيذ الحذف؟`, async () => {
                try {
                    const expected = (plan.delete || []).map((row) => row.timestamp);
                    const result = await this.call("apply_retention_now", { settings_json: settingsJson, expected_timestamps: JSON.stringify(expected) });
                    this.showAlert(`${result.message} عدد الملفات المحذوفة: ${result.deleted_count}`, "success");
                    await this.load();
                } catch (error) { this.showAlert("تعذر تنفيذ سياسة الاحتفاظ. أعد المعاينة إذا تغيرت القائمة.", "danger"); }
            });
        } catch (error) { this.showAlert("تعذر حساب سياسة الاحتفاظ قبل الحذف.", "danger"); }
    }

    async startBackup() {
        const saved = this.currentBackupSettings || {};
        const selectedMode = this.body.find("#backup-mode").val() || "scheduled";
        const selectedPath = (this.body.find("#backup-local-path").val() || "").trim();
        const savedPath = ((saved.storage || {}).local_path || "").trim();
        const selectedMount = this.body.find("#backup-require-mount").is(":checked");
        const savedMount = !!((saved.storage || {}).require_mount);
        if (selectedMode !== (saved.backup_mode || "scheduled") || selectedPath !== savedPath || selectedMount !== savedMount) {
            frappe.msgprint("احفظ نمط النسخ ومسار التخزين أولاً قبل بدء النسخ.");
            return;
        }
        if (selectedMode === "one_time" && saved.one_time_completed_at) {
            frappe.msgprint("تم تنفيذ النسخة المحددة لمرة واحدة بالفعل.");
            return;
        }
        frappe.confirm("هل تريد بدء إنشاء نسخة كاملة الآن، بما في ذلك مصادر التطبيقات المحددة؟", async () => {
            this.showAlert("تم إرسال الطلب. يجري إنشاء نسخة قاعدة البيانات والملفات ثم أرشفة مصادر التطبيقات...", "info");
            try { await this.call("start_backup"); this.pollBackup(0); }
            catch (error) { this.showAlert("تعذر بدء النسخ الاحتياطي. راجع سجل خدمة hded-erp-backup.", "danger"); }
        });
    }

    pollBackup(attempt) {
        setTimeout(async () => {
            try {
                const data = await this.call("get_dashboard");
                this.renderData(data);
                if (data.status && data.status.service_active && attempt < 540) {
                    this.showAlert("لا تزال عملية النسخ تعمل، بما في ذلك أرشفة التطبيقات. سيتم تحديث الحالة تلقائياً...", "info");
                    this.pollBackup(attempt + 1);
                    return;
                }
                if (data.status && data.status.service_result === "success") this.showAlert("اكتملت عملية النسخ الاحتياطي بنجاح.", "success");
                else this.showAlert("انتهت عملية النسخ مع خطأ أو لم تكتمل أرشفة التطبيقات. راجع سجل hded-erp-backup.", "danger");
            } catch (error) {
                if (attempt < 540) this.pollBackup(attempt + 1);
                else this.showAlert("تعذر متابعة حالة عملية النسخ. راجع سجل خدمة hded-erp-backup.", "danger");
            }
        }, 5000);
    }

    async verify(timestamp, storage = "active") {
        this.showAlert("يتم فحص ملفات النسخة وأرشيف التطبيقات إن وجد...", "info");
        try {
            const result = await this.call("verify_backup", { timestamp, storage });
            const detail = (result.checks || []).map((check) => `${check.ok ? "✓" : "✗"} ${check.name}`).join(" — ");
            this.showAlert(`${result.message || "انتهى الفحص"}${detail ? " | " + detail : ""}`, result.ok ? "success" : "danger");
        } catch (error) { this.showAlert("تعذر فحص النسخة الاحتياطية.", "danger"); }
    }

    download(filename, storage = "active") { window.location.href = `/api/method/hded_backup_manager.api.download_backup?filename=${encodeURIComponent(filename)}&storage=${encodeURIComponent(storage)}`; }
    showAlert(message, type) { this.body.find("#backup-alert").removeClass("alert-info alert-success alert-danger").addClass(`alert alert-${type}`).text(message).show(); }
    hideAlert() { this.body.find("#backup-alert").hide(); }
}
