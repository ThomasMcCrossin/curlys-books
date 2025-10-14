export default function Home() {
  return (
    <>
      <script dangerouslySetInnerHTML={{
        __html: `
          if (window.location.hostname === 'review.curlys.ca') {
            window.location.href = '/review';
          }
        `
      }} />
      <main>
        <h1>Curly's Books</h1>
        <p>Coming soon...</p>
      </main>
    </>
  );
}