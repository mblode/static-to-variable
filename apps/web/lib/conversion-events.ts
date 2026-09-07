import posthog from "posthog-js";

export const captureConversion = ({
  action,
  event = "cta_clicked",
  href,
  label,
}: {
  action: string;
  event?: "cta_clicked" | "download_clicked";
  href: string;
  label: string;
}) => {
  try {
    const { pathname } = window.location;
    posthog.capture(event, {
      $current_url: `https://blode.co${pathname}`,
      $pathname: pathname,
      action,
      href,
      label,
      location: pathname,
      product: "static-to-variable",
    });
  } catch {
    // Analytics must never prevent a copy or navigation.
  }
};
