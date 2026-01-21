import { render, screen } from '@testing-library/react-native';
import Index from '../app/(tabs)/index';

describe('<Index />', () => {
  it('renders chat tab content', () => {
    render(<Index />);
    expect(screen.getByText(/chat/i)).toBeTruthy();
  });
});
