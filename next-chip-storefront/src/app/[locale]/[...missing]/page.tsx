import { notFound } from "next/navigation";

/** Any unknown path under a locale renders the localized 404 inside the site shell. */
export default function Missing() {
  notFound();
}
