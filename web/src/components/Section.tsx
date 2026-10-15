import type { ReactNode } from "react";
import { Reveal } from "./Motion";

/** Numbered section: "■ 004 ■ OPEN DRIFT" bar, sticky label column, body. */
export function Section({ id, index, kicker, title, intro, aside, children }: {
  id: string; index: string; kicker: string; title: string; intro: ReactNode; aside?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="sec" id={id}>
      <div className="sec__bar mono"><span><i className="sq" />{index}</span><span><i className="sq" />{kicker}</span></div>
      <Reveal className="sec__label">
        <h2>{title}</h2>
        <p>{intro}</p>
        {aside}
      </Reveal>
      <Reveal className="sec__body" delay={0.08}>{children}</Reveal>
    </section>
  );
}
