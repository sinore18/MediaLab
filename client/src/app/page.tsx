import Link from "next/link";
import { ArrowDownRight, ArrowRight, AudioLines, Check, CirclePlay, FileVideo2, Sparkles } from "lucide-react";

const waveformHeights = [
  20, 32, 24, 42, 30, 52, 37, 26, 44, 58, 34, 48, 25, 39, 54, 29, 43, 61, 35, 46, 26, 52, 38, 22,
  43, 57, 32, 47, 28, 54, 39, 24, 46, 60, 34, 43, 26, 51, 36, 22, 42, 57, 31, 48, 27, 40, 55, 33,
];

export default function Home() {
  return (
    <main className="landing">
      <header className="landing-header">
        <Link className="brand" href="/" aria-label="Bleeper home">
          <span className="brand-mark"><FileVideo2 size={19} strokeWidth={2.2} /></span>
          <span>bleeper</span>
        </Link>
        <nav className="landing-nav" aria-label="Main navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#made-for">Made for creators</a>
          <Link href="/transcribe">Transcribe audio</Link>
        </nav>
        <Link className="header-cta" href="/transcribe">
          Audio studio <ArrowRight size={15} />
        </Link>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow"><span className="eyebrow-dot" /> A cleaner cut, in a few clicks</p>
          <h1 id="hero-title">Keep the story.<br /><span>Lose the words.</span></h1>
          <p className="hero-description">
            Give every video a little polish. Bleeper helps you clean up the audio while keeping the moment intact.
          </p>
          <div className="hero-actions">
            <Link className="primary-cta" href="/upload">
              Check it out <ArrowRight size={17} />
            </Link>
            <Link className="text-cta" href="/transcribe"><AudioLines size={17} /> Transcribe audio</Link>
            <a className="text-cta" href="#how-it-works"><CirclePlay size={18} /> See how it works</a>
          </div>
          <div className="hero-proof">
            <span className="proof-check"><Check size={13} /></span>
            <span>Your original video stays untouched</span>
          </div>
        </div>

        <div className="hero-visual" aria-label="Illustration of a video audio track being cleaned up">
          <div className="visual-orbit orbit-one" />
          <div className="visual-orbit orbit-two" />
          <div className="float-note note-top"><Sparkles size={14} /> SOUND, SORTED</div>
          <div className="editor-card">
            <div className="editor-topline">
              <div className="editor-file"><span className="editor-file-icon"><FileVideo2 size={16} /></span><span>weekend-recap.mp4</span></div>
              <span className="editor-duration">00:18</span>
            </div>
            <div className="video-frame">
              <div className="frame-sun" />
              <div className="frame-hill hill-back" />
              <div className="frame-hill hill-front" />
              <div className="frame-caption">A moment worth keeping.</div>
              <span className="play-control"><CirclePlay size={42} strokeWidth={1.4} /></span>
              <span className="frame-time">00:07 / 00:18</span>
            </div>
            <div className="track-label"><AudioLines size={14} /><span>AUDIO TRACK</span><span className="track-state"><span /> CLEANED</span></div>
            <div className="waveform" aria-hidden="true">
              {waveformHeights.map((height, index) => (
                <span
                  className={index >= 20 && index <= 25 ? "wave-bar wave-bar-muted" : "wave-bar"}
                  style={{ height: `${height}px` }}
                  key={index}
                />
              ))}
              <span className="playhead" />
            </div>
            <div className="track-markers"><span>00:00</span><span>00:09</span><span>00:18</span></div>
          </div>
          <div className="float-note note-bottom"><span className="note-wave"><AudioLines size={15} /></span> ORIGINAL PRESERVED</div>
          <span className="visual-spark spark-one">✳</span>
          <span className="visual-spark spark-two">✳</span>
        </div>
        <a className="scroll-cue" href="#how-it-works" aria-label="Scroll to how it works"><ArrowDownRight size={17} /><span>SCROLL TO EXPLORE</span></a>
      </section>

      <section className="how-section" id="how-it-works" aria-labelledby="how-title">
        <div className="section-heading">
          <p className="eyebrow"><span className="eyebrow-dot" /> A smoother workflow</p>
          <h2 id="how-title">Less editing. More <em>being there.</em></h2>
        </div>
        <div className="steps-grid">
          <article className="landing-step">
            <span className="step-index">01</span>
            <div className="step-icon"><FileVideo2 size={20} /></div>
            <h3>Bring your video</h3>
            <p>Drop in a clip up to 10 minutes long and let the studio take it from here.</p>
          </article>
          <article className="landing-step">
            <span className="step-index">02</span>
            <div className="step-icon step-icon-accent"><AudioLines size={20} /></div>
            <h3>Clean up the audio</h3>
            <p>Give the rough edges a bleep without losing the flow of your video.</p>
          </article>
          <article className="landing-step">
            <span className="step-index">03</span>
            <div className="step-icon"><ArrowDownRight size={20} /></div>
            <h3>Take it with you</h3>
            <p>Preview your finished cut, then download it and share it your way.</p>
          </article>
        </div>
      </section>

      <section className="closing-banner" id="made-for">
        <div>
          <p className="eyebrow"><span className="eyebrow-dot" /> Your next cut starts here</p>
          <h2>Make room for the good stuff.</h2>
        </div>
        <Link className="primary-cta" href="/upload">Check it out <ArrowRight size={17} /></Link>
      </section>
      <footer className="landing-footer">
        <Link className="brand" href="/" aria-label="Bleeper home">
          <span className="brand-mark"><FileVideo2 size={17} strokeWidth={2.2} /></span>
          <span>bleeper</span>
        </Link>
        <span>Keep the story. Lose the words.</span>
      </footer>
    </main>
  );
}
