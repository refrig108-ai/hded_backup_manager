# HDED Backup Manager 0.3.0

مدير النسخ الاحتياطي لـ ERPNext 16 وFrappe 16.

## المزايا
- النسخ الاحتياطي باستخدام Bench الرسمي.
- نسخ ملفات الموقع العامة والخاصة.
- أرشفة مصادر التطبيقات.
- فحص سلامة النسخ.
- جدولة يومية وأسبوعية وشهرية.
- إدارة الاحتفاظ بالنسخ.
- اختيار مجلد نسخ محلي على قرص داخلي أو خارجي.
- فحص المجلد والصلاحيات والمساحة المتاحة والتحقق من اتصال القرص الخارجي عند اشتراطه.
- الإبقاء على النسخ القديمة ظاهرة بعد تغيير مسار التخزين.
- واجهة عربية محمية بدور System Manager.

## المتطلبات
- Ubuntu أو Linux مع systemd.
- Frappe 16 وERPNext 16.
- Bench وبيئة Python باسم env.
- مستخدم Linux يشغّل Bench.

## التثبيت

تنزيل التطبيق:

    bench get-app --branch main https://github.com/refrig108-ai/hded_backup_manager.git

تثبيته على الموقع:

    bench --site YOUR_SITE install-app hded_backup_manager

تثبيت خدمة النسخ:

    sudo bash apps/hded_backup_manager/scripts/install_systemd.sh --bench-dir "$PWD" --site YOUR_SITE --user YOUR_LINUX_USER

استبدل YOUR_SITE باسم الموقع وYOUR_LINUX_USER بمستخدم Linux.

إذا كان مؤقت HDED موجوداً مسبقاً، يحافظ المثبت على جدولته وحالته الحالية.

## المنطقة الزمنية

    sudo timedatectl set-timezone Asia/Aden

## صفحة التطبيق

    /app/backup-manager

## التحقق من الخدمة

    sudo /usr/local/sbin/hded-backup-control status
    systemctl list-timers hded-erp-backup.timer --all
    journalctl -u hded-erp-backup.service -n 100 --no-pager

## التحديث

    git -C apps/hded_backup_manager pull --ff-only
    ./env/bin/python -m pip install --no-deps --no-build-isolation -e apps/hded_backup_manager
    bench build --app hded_backup_manager
    bench --site YOUR_SITE clear-cache
    sudo supervisorctl restart 'medical-erp16-bench-web:*'

## إزالة خدمات النظام

    sudo bash apps/hded_backup_manager/scripts/uninstall_systemd.sh

الإزالة لا تحذف ملفات النسخ الاحتياطية أو إعدادات الموقع.

## التخزين المحلي

يمكن ترك مسار التخزين فارغاً لاستخدام المسار الافتراضي داخل مجلد الموقع، أو إدخال مسار مطلق مثل:

    /mnt/backup-drive/hded-backups

عند اختيار قرص خارجي، فعّل خيار اشتراط وجود وحدة تخزين منفصلة. سيوقف مدير النسخ عملية النسخ إذا لم يكن القرص مركباً، حتى لا تُكتب النسخ بالخطأ على قرص النظام. أدخل مجلداً فرعياً داخل نقطة التركيب، ولا تختَر نقطة تركيب القرص نفسها. تغيير المسار لا ينقل النسخ القديمة ولا يحذفها؛ يحتفظ التطبيق بسجل لمسارات التخزين السابقة ويعرض النسخ الموجودة فيها تحت تسمية "مجلد سابق". سياسة الاحتفاظ تطبق على المسار النشط فقط.

يجب أن يكون مجلد التخزين آمناً بصلاحيات المالك فقط (0700)، وأن يكون قابلاً للكتابة بواسطة مستخدم خدمات ERPNext.

## الربط الخارجي

Google Drive وOneDrive لا ينفذان رفعاً سحابياً فعلياً في هذا الإصدار.
البريد يستخدم نموذج Email Account القياسي في ERPNext.

## الأمان

لا ترفع ملفات النسخ الاحتياطية أو إعدادات المواقع أو مفاتيح الوصول إلى GitHub.
