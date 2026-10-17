import { useRef, type ReactNode } from "react";
import { gsap, moving, revealHeading, useGSAP } from "../lib/gsap";

/** A working section: "01" index, title and one-line intro on the left, controls on the right, body below.
    On scroll: the title rises word by word, the accent hairline draws, and the body tilts up out of the page. */
export function Section({ id, index, title, intro, aside, children }: {
  id: string; index: string; title: string; intro: ReactNode; aside?: ReactNode; children: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    const head = el.querySelector(".sec__head"), body = el.querySelector(".sec__body");
    const when = { trigger: head, start: "top 85%", once: true };
    revealHeading(el.querySelector(".sec__head h2"));
    gsap.fromTo(head, { "--bar": 0 }, { "--bar": 1, duration: 1.4, ease: "expo.inOut", scrollTrigger: when });
    gsap.from(el.querySelectorAll(".sec__num, .sec__head p, .sec__aside"), { opacity: 0, y: 14, stagger: 0.08, delay: 0.15, scrollTrigger: when });
    // the body tips up from the page in 3D; transforms are cleared after so fullscreen graphs inside stay viewport-fixed
    gsap.from(body, {
      rotationX: 16, y: 90, opacity: 0, transformPerspective: 1400, transformOrigin: "50% 0%", duration: 1.3, ease: "expo.out",
      clearProps: "transform,opacity", scrollTrigger: { trigger: body, start: "top 94%", once: true },
    });
  }, { scope: ref });
  return (
    <section className="sec" id={id} ref={ref}>
      <div className="sec__head">
        <span className="sec__num">{index}</span>
        <div>
          <h2>{title}</h2>
          <p>{intro}</p>
        </div>
        {aside && <div className="sec__aside">{aside}</div>}
      </div>
      <div className="sec__body">{children}</div>
    </section>
  );
}
