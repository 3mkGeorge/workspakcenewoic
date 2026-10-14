/**
 * DEMO FIXTURES — sample data for development and demonstrations only.
 * Nothing here reflects live Next Chip inventory, prices or delivery terms.
 */
import type { Brand, Category, Governorate, LocalizedText, PaymentMethod, Promotion, ShippingZone } from "@/lib/commerce/types";

export const DEMO_CATEGORIES: Category[] = [
  {
    id: "cat-mice",
    slug: "gaming-mice",
    icon: "mouse",
    sortOrder: 1,
    name: { en: "Gaming Mice", ar: "ماوس الألعاب" },
    description: {
      en: "Lightweight wired and wireless mice tuned for precise aim.",
      ar: "ماوسات سلكية ولاسلكية خفيفة لتصويب دقيق.",
    },
  },
  {
    id: "cat-mousepads",
    slug: "mousepads",
    icon: "mousepad",
    sortOrder: 2,
    name: { en: "Mousepads", ar: "ماوس باد" },
    description: { en: "Control, speed and hybrid cloth or glass surfaces.", ar: "أسطح قماش أو زجاج للتحكم والسرعة." },
  },
  {
    id: "cat-skates",
    slug: "mouse-skates",
    icon: "skates",
    sortOrder: 3,
    name: { en: "Mouse Skates", ar: "سكيتس الماوس" },
    description: { en: "PTFE and glass feet for a smoother glide.", ar: "أرجل PTFE وزجاجية لانزلاق أنعم." },
  },
  {
    id: "cat-keyboards",
    slug: "keyboards",
    icon: "keyboard",
    sortOrder: 4,
    name: { en: "Keyboards", ar: "الكيبوردات" },
    description: { en: "Mechanical and magnetic keyboards in every layout.", ar: "كيبوردات ميكانيكية ومغناطيسية بكل المقاسات." },
  },
  {
    id: "cat-audio",
    slug: "headsets-iems",
    icon: "headset",
    sortOrder: 5,
    name: { en: "Headsets & IEMs", ar: "سماعات رأس وأذن" },
    description: { en: "Positional audio for competitive play and long sessions.", ar: "صوت محيطي دقيق للعب التنافسي والجلسات الطويلة." },
  },
  {
    id: "cat-mics",
    slug: "microphones",
    icon: "microphone",
    sortOrder: 6,
    name: { en: "Microphones", ar: "الميكروفونات" },
    description: { en: "USB and XLR mics for streaming and voice chat.", ar: "ميكروفونات USB وXLR للبث والدردشة الصوتية." },
  },
  {
    id: "cat-cables",
    slug: "cables-accessories",
    icon: "cable",
    sortOrder: 7,
    name: { en: "Cables & Accessories", ar: "كابلات وإكسسوارات" },
    description: { en: "Paracord cables, bungees, grips and the small upgrades.", ar: "كابلات باراكورد وحوامل وجريبات وترقيات صغيرة." },
  },
];

export const DEMO_BRANDS: Brand[] = [
  { id: "brand-vortek", slug: "vortek", name: "Vortek" },
  { id: "brand-nexa", slug: "nexa-labs", name: "Nexa Labs" },
  { id: "brand-kinetiq", slug: "kinetiq", name: "Kinetiq" },
  { id: "brand-glidex", slug: "glidex", name: "Glidex" },
  { id: "brand-halcyon", slug: "halcyon-audio", name: "Halcyon Audio" },
  { id: "brand-sonaris", slug: "sonaris", name: "Sonaris" },
  { id: "brand-fluxline", slug: "fluxline", name: "Fluxline" },
];

/** Egypt's 27 governorates (ids are stable slugs used in orders and shipping quotes). */
export const GOVERNORATES: Governorate[] = [
  ["cairo", "Cairo", "القاهرة"],
  ["giza", "Giza", "الجيزة"],
  ["qalyubia", "Qalyubia", "القليوبية"],
  ["alexandria", "Alexandria", "الإسكندرية"],
  ["beheira", "Beheira", "البحيرة"],
  ["dakahlia", "Dakahlia", "الدقهلية"],
  ["damietta", "Damietta", "دمياط"],
  ["gharbia", "Gharbia", "الغربية"],
  ["kafr-el-sheikh", "Kafr El Sheikh", "كفر الشيخ"],
  ["monufia", "Monufia", "المنوفية"],
  ["sharqia", "Sharqia", "الشرقية"],
  ["port-said", "Port Said", "بورسعيد"],
  ["ismailia", "Ismailia", "الإسماعيلية"],
  ["suez", "Suez", "السويس"],
  ["faiyum", "Faiyum", "الفيوم"],
  ["beni-suef", "Beni Suef", "بني سويف"],
  ["minya", "Minya", "المنيا"],
  ["asyut", "Asyut", "أسيوط"],
  ["sohag", "Sohag", "سوهاج"],
  ["qena", "Qena", "قنا"],
  ["luxor", "Luxor", "الأقصر"],
  ["aswan", "Aswan", "أسوان"],
  ["red-sea", "Red Sea", "البحر الأحمر"],
  ["new-valley", "New Valley", "الوادي الجديد"],
  ["matrouh", "Matrouh", "مطروح"],
  ["north-sinai", "North Sinai", "شمال سيناء"],
  ["south-sinai", "South Sinai", "جنوب سيناء"],
].map(([id, en, ar]) => ({ id: id!, name: { en: en!, ar: ar! } }));

/** DEMO shipping rates (illustrative values, not a delivery commitment). */
export const DEMO_SHIPPING_ZONES: ShippingZone[] = [
  { id: "greater-cairo", name: { en: "Greater Cairo", ar: "القاهرة الكبرى" }, governorates: ["cairo", "giza", "qalyubia"], fee: 6000 },
  {
    id: "delta-alex",
    name: { en: "Alexandria & Delta", ar: "الإسكندرية والدلتا" },
    governorates: ["alexandria", "beheira", "dakahlia", "damietta", "gharbia", "kafr-el-sheikh", "monufia", "sharqia"],
    fee: 7500,
  },
  { id: "canal", name: { en: "Canal cities", ar: "مدن القناة" }, governorates: ["port-said", "ismailia", "suez"], fee: 7500 },
  {
    id: "upper-egypt",
    name: { en: "Upper Egypt", ar: "الصعيد" },
    governorates: ["faiyum", "beni-suef", "minya", "asyut", "sohag", "qena", "luxor", "aswan"],
    fee: 9500,
  },
  {
    id: "frontier",
    name: { en: "Frontier governorates", ar: "المحافظات الحدودية" },
    governorates: ["red-sea", "new-valley", "matrouh", "north-sinai", "south-sinai"],
    fee: 12000,
  },
];

const L = (en: string, ar: string): LocalizedText => ({ en, ar });

/** Demo payment configuration: cash on delivery only. Card/wallet need a configured gateway. */
export const DEMO_PAYMENT_METHODS: PaymentMethod[] = [
  {
    id: "cod",
    enabled: true,
    label: L("Cash on delivery", "الدفع عند الاستلام"),
    description: L("Pay the courier in cash when your order arrives.", "ادفع نقدًا للمندوب عند استلام طلبك."),
  },
  {
    id: "card",
    enabled: false,
    label: L("Card", "بطاقة"),
    description: L("Requires a configured payment gateway.", "يتطلب إعداد بوابة دفع."),
  },
];

export const DEMO_PROMOTIONS: Promotion[] = [
  {
    id: "promo-aim-season",
    title: L("Aim season", "موسم التصويب"),
    body: L(
      "Selected sample mice and skates at demo sale prices while the promotion runs.",
      "ماوسات وسكيتس مختارة بأسعار عرض تجريبية طوال فترة العرض.",
    ),
    href: "/products?category=gaming-mice&sort=price-asc",
    startsAt: "2026-10-01T00:00:00+02:00",
    endsAt: "2026-11-30T23:59:59+02:00",
    productIds: ["p-vortek-v1-air", "p-nexa-falcon-pro", "p-glidex-dots-pro"],
  },
  {
    // Expired on purpose: must never be displayed.
    id: "promo-summer-sync",
    title: L("Summer sync", "عرض الصيف"),
    body: L("Expired sample promotion.", "عرض تجريبي منتهي."),
    href: "/products?category=keyboards",
    startsAt: "2026-06-01T00:00:00+03:00",
    endsAt: "2026-08-31T23:59:59+03:00",
    productIds: ["p-kinetiq-k75"],
  },
];
